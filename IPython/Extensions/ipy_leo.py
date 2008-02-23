""" ILeo - Leo plugin for IPython

   
"""
import IPython.ipapi
import IPython.genutils
import IPython.generics
from IPython.hooks import CommandChainDispatcher
import re
import UserDict
from IPython.ipapi import TryNext 

ip = IPython.ipapi.get()
leo = ip.user_ns['leox']
c,g = leo.c, leo.g

# will probably be overwritten by user, but handy for experimentation early on
ip.user_ns['c'] = c
ip.user_ns['g'] = g


from IPython.external.simplegeneric import generic 
import pprint

def es(s):    
    g.es(s, tabName = 'IPython')
    pass

@generic
def format_for_leo(obj):
    """ Convert obj to string representiation (for editing in Leo)"""
    return pprint.pformat(obj)

@format_for_leo.when_type(list)
def format_list(obj):
    return "\n".join(str(s) for s in obj)

attribute_re = re.compile('^[a-zA-Z_][a-zA-Z0-9_]*$')
def valid_attribute(s):
    return attribute_re.match(s)    

def all_cells():
    d = {}
    for p in c.allNodes_iter():
        h = p.headString()
        if h.startswith('@a '):
            d[h.lstrip('@a ').strip()] = p.parent().copy()
        elif not valid_attribute(h):
            continue 
        d[h] = p.copy()
    return d    
    


def eval_node(n):
    body = n.b    
    if not body.startswith('@cl'):
        # plain python repr node, just eval it
        return ip.ev(n.b)
    # @cl nodes deserve special treatment - first eval the first line (minus cl), then use it to call the rest of body
    first, rest = body.split('\n',1)
    tup = first.split(None, 1)
    # @cl alone SPECIAL USE-> dump var to user_ns
    if len(tup) == 1:
        val = ip.ev(rest)
        ip.user_ns[n.h] = val
        es("%s = %s" % (n.h, repr(val)[:20]  )) 
        return val

    cl, hd = tup 

    xformer = ip.ev(hd.strip())
    es('Transform w/ %s' % repr(xformer))
    return xformer(rest, n)

class LeoNode(object, UserDict.DictMixin):
    """ Node in Leo outline
    
    Most important attributes (getters/setters available:
     .v     - evaluate node, can also be alligned 
     .b, .h - body string, headline string
     .l     - value as string list
    
    Also supports iteration, 
    
    setitem / getitem (indexing):  
     wb.foo['key'] = 12
     assert wb.foo['key'].v == 12
    
    Note the asymmetry on setitem and getitem! Also other
    dict methods are available. 
    
    .ipush() - run push-to-ipython
    
    """
    def __init__(self,p):
        self.p = p.copy()

    def __get_h(self): return self.p.headString()
    def __set_h(self,val):
        print "set head",val
        c.beginUpdate() 
        try:
            c.setHeadString(self.p,val)
        finally:
            c.endUpdate()
        
    h = property( __get_h, __set_h, doc = "Node headline string")  

    def __get_b(self): return self.p.bodyString()
    def __set_b(self,val):
        print "set body",val
        c.beginUpdate()
        try: 
            c.setBodyString(self.p, val)
        finally:
            c.endUpdate()
    
    b = property(__get_b, __set_b, doc = "Nody body string")
    
    def __set_val(self, val):        
        self.b = format_for_leo(val)
        
    v = property(lambda self: eval_node(self), __set_val, doc = "Node evaluated value")
    
    def __set_l(self,val):
        self.b = '\n'.join(val )
    l = property(lambda self : IPython.genutils.SList(self.b.splitlines()), 
                 __set_l, doc = "Node value as string list")
    
    def __iter__(self):
        """ Iterate through nodes direct children """
        
        return (LeoNode(p) for p in self.p.children_iter())

    def __children(self):
        d = {}
        for child in self:
            head = child.h
            tup = head.split(None,1)
            if len(tup) > 1 and tup[0] == '@k':
                d[tup[1]] = child
                continue
            
            if not valid_attribute(head):
                d[head] = child
                continue
        return d
    def keys(self):
        d = self.__children()
        return d.keys()
    def __getitem__(self, key):
        """ wb.foo['Some stuff'] Return a child node with headline 'Some stuff'
        
        If key is a valid python name (e.g. 'foo'), look for headline '@k foo' as well
        """  
        key = str(key)
        d = self.__children()
        return d[key]
    def __setitem__(self, key, val):
        """ You can do wb.foo['My Stuff'] = 12 to create children 
        
        This will create 'My Stuff' as a child of foo (if it does not exist), and 
        do .v = 12 assignment.
        
        Exception:
        
        wb.foo['bar'] = 12
        
        will create a child with headline '@k bar', because bar is a valid python name
        and we don't want to crowd the WorkBook namespace with (possibly numerous) entries
        """
        key = str(key)
        d = self.__children()
        if key in d:
            d[key].v = val
            return
        
        if not valid_attribute(key):
            head = key
        else:
            head = '@k ' + key
        p = c.createLastChildNode(self.p, head, '')
        LeoNode(p).v = val
    def __delitem__(self,key):
        pass
    def ipush(self):
        """ Does push-to-ipython on the node """
        push_from_leo(self)
    def go(self):
        """ Set node as current node (to quickly see it in Outline) """
        c.beginUpdate()
        try:
            c.setCurrentPosition(self.p)
        finally:
            c.endUpdate()  
        
    def __get_uA(self):
        p = self.p
        # Create the uA if necessary.
        if not hasattr(p.v.t,'unknownAttributes'):
            p.v.t.unknownAttributes = {}        
        
        d = p.v.t.unknownAttributes.setdefault('ipython', {})
        return d        
    uA = property(__get_uA, doc = "Access persistent unknownAttributes of node'")
        

class LeoWorkbook:
    """ class for 'advanced' node access 
    
    Has attributes for all "discoverable" nodes. Node is discoverable if it 
    either
    
    - has a valid python name (Foo, bar_12)
    - is a parent of an anchor node (if it has a child '@a foo', it is visible as foo)
    
    """
    def __getattr__(self, key):
        if key.startswith('_') or key == 'trait_names' or not valid_attribute(key):
            raise AttributeError
        cells = all_cells()
        p = cells.get(key, None)
        if p is None:
            p = add_var(key)

        return LeoNode(p)

    def __str__(self):
        return "<LeoWorkbook>"
    def __setattr__(self,key, val):
        raise AttributeError("Direct assignment to workbook denied, try wb.%s.v = %s" % (key,val))
        
    __repr__ = __str__
    
    def __iter__(self):
        """ Iterate all (even non-exposed) nodes """
        cells = all_cells()
        return (LeoNode(p) for p in c.allNodes_iter())
    
ip.user_ns['wb'] = LeoWorkbook()



@IPython.generics.complete_object.when_type(LeoWorkbook)
def workbook_complete(obj, prev):
    return all_cells().keys()
    

def add_var(varname):
    c.beginUpdate()
    try:
        p2 = g.findNodeAnywhere(c,varname)
        if p2:
            return

        rootpos = g.findNodeAnywhere(c,'@ipy-results')
        if not rootpos:
            rootpos = c.currentPosition() 
        p2 = rootpos.insertAsLastChild()
        c.setHeadString(p2,varname)
        return p2
    finally:
        c.endUpdate()

def add_file(self,fname):
    p2 = c.currentPosition().insertAfter()

push_from_leo = CommandChainDispatcher()

def expose_ileo_push(f, prio = 0):
    push_from_leo.add(f, prio)

def push_ipython_script(node):
    """ Execute the node body in IPython, as if it was entered in interactive prompt """
    c.beginUpdate()
    try:
        ohist = ip.IP.output_hist 
        hstart = len(ip.IP.input_hist)
        script = g.getScript(c,node.p,useSelectedText=False,forcePythonSentinels=False,useSentinels=False)
        
        script = g.splitLines(script + '\n')
        
        ip.runlines(script)
        
        has_output = False
        for idx in range(hstart,len(ip.IP.input_hist)):
            val = ohist.get(idx,None)
            if val is None:
                continue
            has_output = True
            inp = ip.IP.input_hist[idx]
            if inp.strip():
                es('In: %s' % (inp[:40], ))
                
            es('<%d> %s' % (idx, pprint.pformat(ohist[idx],width = 40)))
        
        if not has_output:
            es('ipy run: %s (%d LL)' %( node.h,len(script)))
    finally:
        c.endUpdate()

# this should be the LAST one that will be executed, and it will never raise TryNext
expose_ileo_push(push_ipython_script, 1000)
    
def eval_body(body):
    try:
        val = ip.ev(body)
    except:
        # just use stringlist if it's not completely legal python expression
        val = IPython.genutils.SList(body.splitlines())
    return val 
    
def push_plain_python(node):
    if not node.h.endswith('P'):
        raise TryNext
    script = g.getScript(c,node.p,useSelectedText=False,forcePythonSentinels=False,useSentinels=False)
    lines = script.count('\n')
    try:
        exec script in ip.user_ns
    except:
        print " -- Exception in script:\n"+script + "\n --"
        raise
    es('ipy plain: %s (%d LL)' % (node.h,lines))
    
expose_ileo_push(push_plain_python, 100)

def push_cl_node(node):
    """ If node starts with @cl, eval it
    
    The result is put to root @ipy-results node
    """
    if not node.b.startswith('@cl'):
        raise TryNext
        
    p2 = g.findNodeAnywhere(c,'@ipy-results')
    val = node.v
    if p2:
        es("=> @ipy-results")
        LeoNode(p2).v = val
    es(val)

expose_ileo_push(push_cl_node,100)

def push_position_from_leo(p):
    push_from_leo(LeoNode(p))   
    
ip.user_ns['leox'].push = push_position_from_leo    
    
def leo_f(self,s):
    """ open file(s) in Leo
    
    Takes an mglob pattern, e.g. '%leo *.cpp' or %leo 'rec:*.cpp'  
    """
    import os
    from IPython.external import mglob
    
    files = mglob.expand(s)
    c.beginUpdate()
    try:
        for fname in files:
            p = g.findNodeAnywhere(c,'@auto ' + fname)
            if not p:
                p = c.currentPosition().insertAfter()
            
            p.setHeadString('@auto ' + fname)
            if os.path.isfile(fname):
                c.setBodyString(p,open(fname).read())
            c.selectPosition(p)
    finally:
        c.endUpdate()

ip.expose_magic('leo',leo_f)

def leoref_f(self,s):
    """ Quick reference for ILeo """
    import textwrap
    print textwrap.dedent("""\
    %leo file - open file in leo
    wb.foo.v  - eval node foo (i.e. headstring is 'foo' or '@ipy foo')
    wb.foo.v = 12 - assign to body of node foo
    wb.foo.b - read or write the body of node foo
    wb.foo.l - body of node foo as string list
    
    for el in wb.foo:
      print el.v
       
    """
    )
ip.expose_magic('leoref',leoref_f)

def show_welcome():
    print "------------------"
    print "Welcome to Leo-enabled IPython session!"
    print "Try %leoref for quick reference."
    import IPython.platutils
    IPython.platutils.set_term_title('ILeo')
    IPython.platutils.freeze_term_title()

def run_leo_startup_node():
    p = g.findNodeAnywhere(c,'@ipy-startup')
    if p:
        print "Running @ipy-startup nodes"
        for n in LeoNode(p):
            push_from_leo(n)

run_leo_startup_node()
show_welcome()

