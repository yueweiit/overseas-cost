"""
中文用途：Frappe 自定义 app 的 Python 安装入口文件。

后续当模块正式接入 bench / ERP 环境时，会通过该文件识别包名、版本和依赖。
"""

from pathlib import Path

from setuptools import find_packages, setup


BASE_DIR = Path(__file__).parent
REQUIREMENTS = BASE_DIR / "requirements.txt"


def get_install_requires() -> list[str]:
    if not REQUIREMENTS.exists():
        return []
    return [
        line.strip()
        for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


setup(
    name="overseas_costing",
    version="0.1.0",
    description="Overseas purchase landed costing module for Frappe",
    author="Yuewei",
    author_email="dev@yuewei.local",
    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,
    install_requires=get_install_requires(),
)
