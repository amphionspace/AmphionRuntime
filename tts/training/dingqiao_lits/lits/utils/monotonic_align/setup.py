from pathlib import Path

import numpy
from Cython.Build import cythonize
from setuptools import Extension, setup


SOURCE = Path(__file__).with_name("core.pyx")

setup(
    name="lits-monotonic-align",
    ext_modules=cythonize(
        [
            Extension(
                "lits.utils.monotonic_align.core",
                [str(SOURCE)],
                include_dirs=[numpy.get_include()],
            )
        ],
        compiler_directives={"language_level": "3"},
    ),
)
