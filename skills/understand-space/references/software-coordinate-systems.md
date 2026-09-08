# 软件坐标约定速查

## 使用边界

本文件由 `understand-space` 维护，供执行空间任务的模型在缺少软件默认约定时定向读取；表内事实来自链接的官方来源，核对日期为 2026-09-08。它是可重建的参考摘要，不是场景配置或矩阵转换的真源。软件版本、API、导入器或项目设置与所引来源不符时，回到对应官方文档及实际状态核对，只更新受影响条目。

先识别软件、对象及空间层级，再使用对应行。默认世界上轴不证明模型实际前向、骨骼轴、相机空间或屏幕原点；单位显示也不证明存储值与导出值的尺度。手性、上轴、矩阵乘法侧与存储顺序分别确认，不能互相推导。没有列出的软件只查当前任务需要的约定，不扩建全软件百科。

## 三维引擎

| 软件与空间 | 默认约定 | 必须区分的情况与官方来源 |
| --- | --- | --- |
| Unreal Engine 世界空间 | 左手；+X 前、+Y 右、+Z 上；默认长度单位 cm | 资产导入方向、组件局部轴和显示单位单独确认；不把这组轴套到屏幕或投影空间。[空间](https://dev.epicgames.com/documentation/en-us/unreal-engine/coordinate-system-and-spaces-in-unreal-engine)、[单位](https://dev.epicgames.com/documentation/unreal-engine/units-of-measurement-in-unreal-engine?lang=en-US) |
| Unity Transform | 左手；+X 右、+Y 上、+Z 前 | 旋转后的局部轴不同于世界轴；`worldToCameraMatrix` 定义的相机空间前向为 −Z，不能按 Transform 的 +Z 前向解释。[Transform 约定](https://docs.unity3d.com/6000.0/Documentation/Manual/QuaternionAndEulerRotationsInUnity.html)、[相机空间](https://docs.unity3d.com/6000.0/Documentation/ScriptReference/Camera-worldToCameraMatrix.html) |
| Godot 三维 | 右手；+Y 上；相机前向 −Z；1 单位为 1 m | 定向模型约定前向 +Z，`MODEL_*` 与相机方向不是同一套语义；资产是否遵循该约定仍需确认。[世界与尺度](https://docs.godotengine.org/en/stable/tutorials/3d/introduction_to_3d.html#coordinate-system)、[模型与相机](https://docs.godotengine.org/en/stable/tutorials/assets_pipeline/importing_3d_scenes/model_export_considerations.html) |

## 建模与 CAD

| 软件与空间 | 默认或可配置项 | 必须区分的情况与官方来源 |
| --- | --- | --- |
| Blender 世界与导出 | Z-up；OBJ 文档以沿 +Y 观察前视图说明其 Forward 约定 | 导出器的 Forward/Up 选项不是任意角色模型的实际面朝方向。Scene Units、Unit Scale 与对象/导出缩放分别确认；Unit Scale 不能当作已重缩放几何或物理行为的证明。[OBJ 轴转换](https://docs.blender.org/manual/en/3.3/files/import_export/obj.html)、[场景单位](https://docs.blender.org/manual/en/latest/scene_layout/scene/properties.html) |
| Maya 世界空间 | 默认 Y-up，可改 Z-up；默认线性单位 cm，可配置 | 先读实际 Up Axis 和 Working Units；不要因软件名覆盖已知场景设置。[Settings preferences](https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Customizing/files/GUID-4D653DC9-57AA-4D8B-987A-5B7A9735CAF0.htm) |
| 3ds Max 世界空间 | 从前视图看 +X 向右、+Z 向上、+Y 远离观察者 | World 不等于当前操作参考系；System Units 决定实际尺度，Display Units 决定显示，不能只读面板单位。[世界轴](https://help.autodesk.com/cloudhelp/2021/ENU/3DSMax-Reference/files/GUID-EA04E754-26AE-462E-9487-2D37CC35FEBA.htm)、[单位](https://help.autodesk.com/cloudhelp/2023/ENU/3DSMax-Customizing/files/GUID-69E92759-6CD9-4663-B993-635D081853D2.htm) |
| AutoCAD WCS / UCS | WCS 是固定世界系；UCS 可移动、旋转，新图初始与 WCS 重合；UCS 按右手规则 | 输入的工作平面与坐标可属于当前 UCS，不能当作 WCS；图纸单位、对象坐标系及导入比例需按实际入口确认。[WCS 与 UCS](https://help.autodesk.com/cloudhelp/2024/ENU/AutoCAD-Core/files/GUID-E658D5E7-EE5C-4A06-BF34-F71CDB363A71.htm) |

## 二维与屏幕入口

| 入口 | 基准约定 | 必须区分的情况与官方来源 |
| --- | --- | --- |
| Windows 桌面 / 客户区 | 屏幕基准与指定窗口客户区分别解释，通常 x 向右、y 向下 | 副屏可有负坐标；DPI 虚拟化、截图缩放和跨屏映射按 [二维屏幕参考](two-dimensional-layout.md#dpi缩放与截图映射) 核对，不能把所有像素视作同单位。 |
| 浏览器 DOM / CSSOM View | 常用视口坐标 x 向右、y 向下，以 CSS px 计 | `client` 相对视口，`page` 相对初始包含块，`screen` 相对屏幕区域；滚动、缩放和设备像素比不能省略。[CSSOM View](https://www.w3.org/TR/cssom-view/) |
| SVG 初始视口与用户空间 | 通常原点左上，+x 右、+y 下 | `viewBox`、嵌套视口与 transform 会改变用户空间到视口的映射，不能把用户单位一律当屏幕像素。[SVG 2 坐标系](https://www.w3.org/TR/SVG2/coords.html) |
| Unity `Camera.WorldToScreenPoint` | 屏幕像素坐标以左下为原点；返回的 z 是距相机的世界单位距离 | 不是左上原点的 UI 坐标，也不是 NDC 深度或纹理 UV；其他 UI API 按自身合同解释。[API](https://docs.unity3d.com/6000.0/Documentation/ScriptReference/Camera.WorldToScreenPoint.html) |

GPU 裁剪、NDC、渲染目标和 UV 的约定见 [裁剪、视口与 UV](clip-viewport-uv.md)，不得用世界坐标对照表替代它们。
