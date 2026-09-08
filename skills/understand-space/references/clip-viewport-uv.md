# 裁剪、视口与 UV

本文件由 `understand-space` 维护，供模型区分投影、二维裁剪和纹理映射；只读当前任务所需章节。API 事实以链接的官方规范为依据（2026-09-08 核对），场景矩阵、渲染状态、纹理与实际消费者仍是运行真源。后端、格式或状态改变后重新核对受影响约定，摘要可从这些来源重建；不维护渲染器实现或通用转换脚本。

## 先区分对象

| 名称 | 表达什么 | 不能直接替代什么 |
| --- | --- | --- |
| 裁剪空间（clip space） | 投影输出的齐次坐标 `(x_c,y_c,z_c,w_c)`，按当前规则裁剪 | NDC、屏幕像素、UI 裁剪矩形 |
| NDC（标准化设备坐标） | 齐次除法后的 `(x_c/w_c,y_c/w_c,z_c/w_c)` | 视口像素或线性相机距离 |
| 视口 / 渲染目标像素 | NDC 经视口位置、尺寸、方向和深度范围映射后的坐标 | 整个桌面、CSS px 或图像文件坐标 |
| UI 裁剪 / scissor / 图像裁切 | 对特定局部区域、渲染目标像素或源图像区域限制输出 | 改变相机投影或重新缩放内容 |
| UV / 纹理坐标 | 表面参数或着色器产生的采样位置，依赖纹理、UV 集、变换与 sampler | 世界坐标、屏幕坐标或图像行列索引 |

投影路径通常为 `对象/世界 → 视图 → clip → NDC → viewport`，二维入口可省略已有恒等阶段。UV 是另一条映射链，只有明确的屏幕空间采样才从屏幕位置导出；不能把所有坐标串成同一条流水线。

## 裁剪与视口

- 确认值是否已经除以 `w`、实际投影矩阵、深度范围和视口。`w = 0` 不可直接除；相机后方或跨裁剪面的点/图元按实际裁剪合同处理，不能先丢弃 `w` 再把投影点落在屏幕内当作可见。透视投影的深度通常非线性，不能直接当世界距离。
- 下表只描述所列状态；默认值不证明当前后端设置。反向深度（reversed-Z）、自定义投影或引擎适配会改变近远映射或轴向；不能从“DirectX/OpenGL”反推世界系手性。

| API / 状态 | 裁剪与除法后的典型范围 | 视口边界与官方来源 |
| --- | --- | --- |
| Direct3D 11，启用深度裁剪 | `w>0`，`−w≤x,y≤w`，`0≤z≤w`；因此 NDC x/y 为 `[-1,1]`，z 为 `[0,1]` | 常规视口将 NDC +y 映射向渲染目标上方，目标像素 y 向下。[裁剪状态](https://learn.microsoft.com/en-us/windows/win32/api/d3d11/ns-d3d11-d3d11_rasterizer_desc)、[视口与 scissor](https://learn.microsoft.com/en-us/windows/win32/direct3d11/d3d10-graphics-programming-guide-rasterizer-stage-getting-started) |
| OpenGL 默认 clip control | NDC x/y/z 为 `[-1,1]`；窗口映射默认 lower-left | `glClipControl` 可选择 upper-left 和 `[0,1]` 深度；不能把默认原点套到所有渲染目标与读回路径。[Khronos 参考源码](https://github.com/KhronosGroup/OpenGL-Refpages/blob/main/gl4/glClipControl.xml) |
| Vulkan 默认深度裁剪 | NDC x/y 为 `[-1,1]`，z 为 `[0,1]` | 正 viewport height 时 y 映射随其正向，负 height 可翻转；扩展也可改为 `[-1,1]` 深度。[深度](https://docs.vulkan.org/guide/latest/depth.html)、[VkViewport](https://docs.vulkan.org/refpages/latest/refpages/source/VkViewport.html) |

UI 裁剪先确认矩形或路径属于哪个节点与坐标系；scissor 按对应 API 的渲染目标坐标解释；源图像 crop 还需明确裁后原点与输出尺寸。裁剪、缩放和 viewport 是不同操作。像素边缘、像素中心、整数索引与右/下边界是否包含分别确认，不把旧后端的半像素修正通用化；例如 [Direct3D 10](https://learn.microsoft.com/en-us/windows/win32/direct3d10/d3d10-graphics-programming-guide-resources-coordinates) 以左上像素的左上角为原点，像素中心偏移 `(0.5,0.5)`。

## UV 与纹理像素

- 确认 mesh UV 集、材质选用的通道、纹理变换、图集子区域、图像尺寸、上传/读回方向及 sampler 寻址模式。归一化 UV 不要求值必须在 `[0,1]` 内，重复、镜像、钳制或分块纹理须按实际合同处理；不要自动截断、翻转 V 或重排 UV。
- UV 编辑器显示朝向、图像存储行序与采样 API 的 `(0,0)` 不是同一事实，也不由软件世界上轴决定。先对应具体入口：

| 入口 | `(0,0)` 的含义 | 边界与官方来源 |
| --- | --- | --- |
| Blender UV Editor 坐标 | 图像左下；可显示相对坐标或像素坐标 | 这是 UV 编辑器显示约定，不证明导出文件未经转换。[UV 导航](https://docs.blender.org/manual/en/latest/editors/uv/navigating.html) |
| Unity `Mesh.uv` | 纹理左下，`(1,1)` 为右上 | 指 UV0 通道；值可超出 `[0,1]`，不外推到任意 render texture 或读回 API。[Mesh.uv](https://docs.unity3d.com/kr/current/ScriptReference/Mesh-uv.html) |
| glTF 2.0 纹理坐标 | 图像左上，`(1,1)` 为右下 | 格式约定，采样的越界行为由 sampler 决定。[纹理坐标与寻址](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#images) |

- 格式、导出器或加载器已经转换过时，不再补一次翻转；先核对实际数据链。
- 只有确认同原点、同方向、整张纹理且按归一化边缘坐标采样时，宽高为 `W,H` 的 texel `(i,j)` 中心才可写成 `((i+0.5)/W,(j+0.5)/H)`；图集、像素中心输入、非归一化采样或方向不同先做相应映射。UV 岛有意重叠不等于几何穿插；是否允许由材质或烘焙合同决定。

## 最小验收

按实际未知选证据，不固定全跑：方向映射可用带不对称角标的图像或已知点；投影可检查视口中心、边缘及当前相关的裁剪边界；UV 可检查纹理方向、边缘与实际使用的越界寻址。纯计算保留输入约定和往返或独立预期；实际画面目标再核对目标后端的读回和渲染。往返自洽不单独证明初始约定正确，两个错误翻转也可能相互抵消。
