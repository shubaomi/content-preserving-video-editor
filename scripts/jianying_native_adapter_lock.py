"""Exact offline wheel set for the Jianying adapter subprocess."""

ADAPTER_WHEEL_FILENAME = "pyjianyingdraft-0.3.0-py3-none-any.whl"
ADAPTER_WHEEL_SHA256 = "09863de4b0cfbb23fff54b4122ef49eff3527685f7978c6230f0651942954bdc"

ADAPTER_DEPENDENCY_LOCK = {
    "comtypes-1.4.16-py3-none-any.whl": "e18d85179ff12955524c5a8c3bc09cb3c0d890f1da4d7123d14244c7b78f84c8",
    "imageio-2.37.4-py3-none-any.whl": "1ab2e22c8debf700f24c3ac43e8f95f3b3a8110c83b93411e97b4b0b2cd1c7e6",
    "numpy-2.5.2-cp313-cp313-win_amd64.whl": "85aaccb24182c25df891ad0ec333585967e115269d5f1b17f2c9ae005bc96657",
    "pillow-12.3.0-cp313-cp313-win_amd64.whl": "1cca606cd25738df4ed873d5ad46bbdb3d83b5cbca291f6b4ff13a4df6b0bbe8",
    "pymediainfo-7.0.1-py3-none-win_amd64.whl": "13224fa7590e198763b8baf072e704ea81d334e71aa32a469091460e243893c7",
    "uiautomation-2.0.29-py3-none-any.whl": "5dd51c9e77e70470142a13d903be67f256c445e7cf20b47ada0ece2bdaff9f32",
}

# This is the exact Windows runtime approved for the WP5 short canary.  A new
# machine/runtime requires an explicit lock refresh; a path that merely looks
# like a virtual environment is not trusted.
ADAPTER_RUNTIME_LOCK = {
    "python_executable_sha256": "6a74478b20739a9c814dcdb465a68cdf384b43447910399e02776d66a2bd1635",
    "pyvenv_cfg_sha256": "c748e3a8111aaf80cd7bb1fcf8c78e685c066d4fb76ae73d15fb18d9b487b46f",
    "python_version": "3.13.12",
    "machine": "AMD64",
    "pointer_bits": 64,
}
