
import os
import sys
import ast
import re
import astpretty

import inspect
import textwrap
import functools
import subprocess
import numpy as np

from config import TARGET_BASE, WORKSPACE
from nodes import plnode_link_parent,plnode_walk
from analyzer import PLAnalyzer, PLTester, ast_link_parent
from typer import PLTyper
from optimizer import PLOptimizer
from codegen import PLCodeGenerator
from sysgen import PLSysGen
from runtime import PLRuntime
import IPinforms
from chaining_rewriter import PLChainingRewriter

PYLOG_KERNELS = dict()

def pylog(func=None, *, mode='cgen', path=WORKSPACE, backend='vhls', \
          board='pynq-z2', freq=None):
    if func is None:
        return functools.partial(pylog, mode=mode, path=path, \
                                 backend=backend, board=board, freq=freq)

    hwgen = 'hwgen' in mode # hwgen = cgen, hls, syn

    # individual steps
    gen_hlsc = hwgen or ('cgen' in mode) or ('codegen' in mode)

    pysim_only = 'pysim' in mode
    deploy = ('deploy' in mode) or ('run' in mode) or ('acc' in mode)
    debug = 'debug' in mode
    timing = 'timing' in mode
    viz = 'viz' in mode

    if freq is None:
        if (board == 'aws_f1' or board.startswith('alveo')):
            freq = 200.0
        else:
            freq = 100.0

    if pysim_only:
        return func

    PYLOG_KERNELS[func.__name__] = func

    @functools.wraps(func)
    def wrapper(*args, **kwargs):

        # builtins = open('builtin.py').read()
        source_func = textwrap.dedent(inspect.getsource(func))
        if debug: print(source_func)
        arg_names = inspect.getfullargspec(func).args

        for arg in args:
            assert (isinstance(arg, (np.ndarray, np.generic)))

        arg_info = {}

        for i in range(len(args)):
            if args[i].dtype.fields is not None:
                key_fields = ''.join(args[i].dtype.fields.keys())
                m1 = re.search('total([0-9]*)bits', key_fields)
                m2 = re.search('dec([0-9]*)bits', key_fields)
                type_name = f'ap_fixed<{m1.group(1)}, {m2.group(1)}>'
            else:
                type_name = args[i].dtype.name

            arg_info[arg_names[i]] = (type_name, args[i].shape)

        # arg_info = { arg_names[i]:(args[i].dtype.name, args[i].shape) \
        #                                           for i in range(len(args)) }

        # num_array_inputs = sum(len(val[1]) != 1 for val in arg_info.values())

        project_path, top_func, max_idx, return_void = pylog_compile(
            src=source_func,
            arg_info=arg_info,
            backend=backend,
            board=board,
            path=path,
            gen_hlsc=gen_hlsc,
            debug=debug,
            viz=viz)

        config = {
            'workspace_base': WORKSPACE,
            'project_name': top_func,
            'project_path': project_path,
            'freq': freq,
            'top_name': top_func,
            'num_bundles': max_idx,
            'timing': timing,
            'board': board,
            'return_void': return_void
        }

        # if run_hls or run_syn or hwgen:
        #     print("generating hardware ...")

        #     plsysgen = PLSysGen(backend=backend, board=board)
        #     plsysgen.generate_system(config, run_hls, run_syn)

        if deploy:
            subprocess.call(f"mkdir -p {TARGET_BASE}/{top_func}/", \
                                      shell=True)

            if board == 'aws_f1' or board.startswith('alveo'):

                ext = 'awsxclbin' if (board == 'aws_f1') else 'xclbin'

                xclbin = f'{top_func}/{top_func}_{board}.{ext}'

            else:

                bit_file = f'{top_func}/{top_func}_{board}.bit'
                hwh_file = f'{top_func}/{top_func}_{board}.hwh'
            plrt = PLRuntime(config)
            return plrt.call(args)

    return wrapper




def pylog_compile(src,gen_hlsc=True, debug=False, viz=False):

    print("Compiling PyLog code ...")

    ast_py = ast.parse(src)
    if debug: astpretty.pprint(ast_py)
    ast_link_parent(ast_py)  # need to be called before analyzer
    # instantiate passes
    tester = PLTester()
    analyzer = PLAnalyzer(debug=debug)
    typer = PLTyper(debug=debug)
    chaining_rewriter = PLChainingRewriter(debug=debug)
    optimizer = PLOptimizer(debug=debug)
    codegen = PLCodeGenerator(debug=debug)

    # execute passes
    if debug:
        tester.visit(ast_py)

    pylog_ir = analyzer.visit(ast_py)
    # astpretty.pprint(pylog_ir)
    if debug:
        print('\n')
        print("pylog IR after analyzer")
        print(pylog_ir)
        print('\n')

    # typer.visit(pylog_ir)

    if debug:
        print('\n')
        print("pylog IR after typer")
        print(pylog_ir)
        print('\n')

    # transform loop transformation and insert pragmas
    optimizer.opt(pylog_ir)

    # need to be called since optimizer may insert new nodes when visiting
    # PLDot or PLMap
    plnode_link_parent(pylog_ir)
    chaining_rewriter.visit(pylog_ir)

    print(getattr(pylog_ir[0].body[0],"value"))
    if debug:
        print('\n')
        print("pylog IR after optimizer")
        print(pylog_ir)
        print('\n')
    path=WORKSPACE
    project_path = f'{path}'

    if not os.path.exists(project_path):
        os.makedirs(project_path)


    hls_c = codegen.codegen(pylog_ir, project_path,debug)

    if debug:
        print("Generated C Code:")
        print(hls_c)

    if gen_hlsc:
        output_file = f'{project_path}.cpp'
        with open(output_file, 'w') as fout:
            fout.write(hls_c)
            print(f"HLS C code written to {output_file}")

    if viz:
        import pylogviz
        pylogviz.show(src, pylog_ir)

    return project_path

with open('example.py') as f:
    code = f.read()
    pylog_compile(code,gen_hlsc=True, debug=False, viz=False)
