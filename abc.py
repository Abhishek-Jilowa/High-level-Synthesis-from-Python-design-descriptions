import ast
import cffi

def convert_ast(node):
    ffi = cffi.FFI()
    ffi.set_source("_module_name", None)
    ffi.cdef(str(ast.dump(node)))
    ffi.compile()

# Example usage
python_code = """
def hello():
    print("Hello, world!")
"""
python_ast = ast.parse(python_code)
c_ast = convert_ast(python_ast)