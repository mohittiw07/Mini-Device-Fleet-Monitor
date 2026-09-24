"""
Root conftest.py

pytest automatically adds the directory containing conftest.py to sys.path,
so that 'from src.xxx import ...' and 'import src.main' work in tests
without needing to install the package.
"""
