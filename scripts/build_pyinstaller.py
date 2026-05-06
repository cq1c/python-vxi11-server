#!/usr/bin/env python3
"""Build the pywebview app with PyInstaller.

The SVG icon is converted to an ICO automatically when CairoSVG and Pillow are
installed. PyInstaller cannot reliably use SVG directly as an application icon,
and Windows executables require an .ico file.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


APP_NAME = 'VISA_Device_Mapping_Tool'
DISPLAY_NAME = 'VISA 设备映射工具'
ICON_SVG = 'automation_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg'

ROOT = Path(__file__).resolve().parents[1]
VIEW_DIR = ROOT / 'view'
VIEW_DIST = VIEW_DIR / 'dist'
ICON_SOURCE = ROOT / ICON_SVG
ICON_DIR = ROOT / 'build' / 'icons'
ICON_ICO = ICON_DIR / 'automation.ico'


def run(cmd: list[str], cwd: Path = ROOT) -> None:
    print(f'+ {" ".join(cmd)}')
    subprocess.run(cmd, cwd=cwd, check=True)


def fail(message: str) -> None:
    raise SystemExit(f'\nERROR: {message}\n')


def ensure_frontend() -> None:
    if not (VIEW_DIR / 'package.json').exists():
        fail('找不到 view/package.json，无法构建前端。')

    if not shutil.which('pnpm'):
        fail('找不到 pnpm。请先安装 Node.js 和 pnpm，然后在 view 目录运行 pnpm install。')

    try:
        run(['pnpm', 'run', 'build-only'], cwd=VIEW_DIR)
    except subprocess.CalledProcessError:
        fail(
            '前端构建失败。若日志中出现 missing native binding / optional '
            'dependencies，请在 view 目录重新安装依赖后重试:\n'
            '  pnpm install'
        )
    if not (VIEW_DIST / 'index.html').exists():
        fail('前端构建后没有生成 view/dist/index.html。')


def convert_svg_to_ico() -> Path:
    if ICON_ICO.exists():
        return ICON_ICO

    if not ICON_SOURCE.exists():
        fail(f'找不到图标文件: {ICON_SOURCE}')

    ICON_DIR.mkdir(parents=True, exist_ok=True)
    try:
        import cairosvg
        from PIL import Image
    except ImportError:
        fail(
            'PyInstaller 不能直接使用 SVG 作为 Windows 应用图标。\n'
            '请安装转换依赖后重试:\n'
            f'  {sys.executable} -m pip install pyinstaller cairosvg pillow\n'
            '脚本会把 automation_24dp_E3E3E3_FILL0_wght400_GRAD0_opsz24.svg '
            '自动转换为 build/icons/automation.ico。'
        )

    try:
        sizes = [16, 24, 32, 48, 64, 128, 256]
        png_files: list[Path] = []
        for size in sizes:
            png = ICON_DIR / f'automation-{size}.png'
            cairosvg.svg2png(
                url=str(ICON_SOURCE),
                write_to=str(png),
                output_width=size,
                output_height=size,
            )
            png_files.append(png)

        base = Image.open(png_files[-1]).convert('RGBA')
        base.save(
            ICON_ICO,
            format='ICO',
            sizes=[(size, size) for size in sizes],
            append_images=[
                Image.open(png).convert('RGBA') for png in png_files[:-1]
            ],
        )
    except Exception as exc:
        fail(
            f'SVG 自动转换 ICO 失败: {exc}\n'
            f'请手动把 {ICON_SOURCE.name} 转换为 {ICON_ICO} 后重试。\n'
            'Windows exe 图标需要 .ico；只传 SVG 给 PyInstaller 通常不会生效。'
        )
    return ICON_ICO


def ensure_pyinstaller() -> None:
    try:
        import PyInstaller.__main__  # noqa: F401
    except ImportError:
        fail(
            '当前 Python 环境没有安装 PyInstaller。\n'
            f'请先运行: {sys.executable} -m pip install pyinstaller'
        )


def pyinstaller_args(icon: Path) -> list[str]:
    separator = ';' if os.name == 'nt' else ':'
    args = [
        sys.executable,
        '-m',
        'PyInstaller',
        '--noconfirm',
        '--clean',
        '--windowed',
        '--name',
        APP_NAME,
        '--icon',
        str(icon),
        '--add-data',
        f'{VIEW_DIST}{separator}view/dist',
        str(ROOT / 'app.py'),
    ]
    return args


def main() -> None:
    print(f'Building {DISPLAY_NAME}')
    ensure_pyinstaller()
    ensure_frontend()
    icon = convert_svg_to_ico()
    run(pyinstaller_args(icon))
    print('\nBuild complete.')
    print(f'Output: {ROOT / "dist" / APP_NAME}')
    if sys.platform.startswith('linux'):
        print(
            '\nNote: Linux window managers may ignore the PyInstaller --icon '
            'setting unless you also install a .desktop file that points to the '
            'icon.'
        )


if __name__ == '__main__':
    main()
