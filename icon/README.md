# 应用图标文件

将你的应用图标放置在此目录：

## 支持的格式

- **Windows**: `app.ico`
- **macOS**: `app.icns`
- **Linux**: `app.png`

## 如何创建图标

### Windows (.ico)
使用在线工具如 [Convertio](https://convertio.co/) 或 GIMP 来创建 .ico 文件，推荐尺寸: 256x256

### macOS (.icns)
使用 `iconutil` 命令行工具或在线转换工具

### Linux (.png)
使用 PNG 格式，推荐尺寸: 256x256

## 注意事项

如果没有提供图标文件，打包脚本将使用 PyInstaller 的默认图标。
