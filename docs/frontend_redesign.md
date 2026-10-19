# MedLit 前端完整重设计（2026-10-20）

## 设计与实现

用户否定上一版视觉后，本轮重做信息架构、导航、主页构图、配色、组件材质和结果阅读顺序。方向是「研究手记」：松绿色主视觉、暖白阅读区、文献索引。首页采用 5/7 的双面板，问题输入是主要操作；结果页依次为检索统计、摘要、PICO、来源，DOM 阅读顺序与视觉顺序一致。

旧 style.css 整体替换，删除叠加用的 refinement.css，页面引用带版本号的新样式。原生 HTML/JavaScript、FastAPI API 和已校验引用协议保留，没有引入框架迁移或新远端运行时。字号仍以桌面摘要 17px、手机 16px 为基准；舒适阅读为 20px / 18px。新拟态仅用于输入材质。

文献列表改为纵向索引，并增加本次结果内的文本查找，支持标题、摘要、作者、期刊、年份和 PMID。筛选不改变总数，并明确显示当前数量；空结果有说明。引用定位会清除遮挡来源的筛选，防止定位到隐藏文献。每次新检索重置本地筛选。

GSAP 继续用于抽屉和阅读操作反馈，保留真实源码适配的 React Bits SpotlightCard 输入高光。减少动态效果会清理动画，库加载失败不影响功能。未添加背景循环动画、虚构进度、装饰性临床图表或未经验证的置信度。

## 实际调研来源与边界

| 来源 | 实际查看内容 | 本轮取舍 |
| --- | --- | --- |
| [Variant](https://variant.com/) | 页面入口和标题，主体依赖客户端渲染 | 未取得可核验的完整案例，不声称复刻其设计 |
| [MotionSites / EasyLog](https://motionsites.org/prompts/3d-bloom-layer) | 公开预览及构图、字体、动效说明 | 参考主视觉的明确焦点；未购买、下载或复制付费源码 |
| [Design Spells / Sudoku a Day](https://designspells.com/spells/smooth-sheet-transitions-in-sudoku-a-day) | 抽屉转场案例和交互分类 | 动作触发反馈，避免长期运行的装饰动画 |
| [Awwwards / Infini](https://www.awwwards.com/sites/infini) | 大字与搜索筛选案例说明 | 参考检索的层级；图库首页抓取超时，没有声称浏览全部案例 |
| [Landbook](https://land-book.com/) | 图库条目、分类及 EADEM 详情 | 图库浏览器加载受限，未将受限页面截图当作成功案例 |
| [Design Everywhere / Science Island](https://designeverywhere.co/work/science-island) | 科学品牌以单一元素贯穿识别系统的说明 | 为 MedLit 自绘「文献—引用」连线图，不复制第三方品牌资产 |
| [Best Designs on X](https://bestdesignsonx.com/) | 公开创作者发现页 | 未登录、未抓取受限帖子，不声称复用某位作者作品 |
| [Bento Grids](https://bentogrids.com/) | 页面入口，正文未能通过读取器取得 | 使用可核验的 21st Bento 集合作布局补充，未臆造条目 |
| [21st.dev Bento 集合](https://21st.dev/community/components/explore/bento-123) | Bento Monochrome、Analytics Bento 等集合条目 | 采用不同宽度的任务面板及整齐边缘，未搬入无关 React 依赖 |
| [React Bits / SpotlightCard](https://reactbits.dev/components/spotlight-card) | 上轮实时下载的 JS-CSS 注册源码及本轮官方页面说明 | 原生 DOM 适配沿用；许可见 static/vendor/ReactBits-LICENSE.md |
| [Eldora UI](https://eldoraui.vercel.app/) | 官方组件展示及可访问性、动效组件文档 | 渐进增强和明确交互状态；未声称安装其 React 组件 |

Taste 使用 app-screen 流程，重抽 Editorial greeting，seed `2100003703`。重抽原因：用户明确要求彻底修改旧设计，原灰蓝配色不再保留。采用真实数据、统一边缘、主任务优先的原则；根据用户要求，主视觉标题保留大字号，文献索引的编号表示真实结果顺序。

## 验证

- Node 回归 17 项通过，包括本轮增加的文本 / PMID 查找、数量说明、无匹配状态、清除，以及引用定位恢复隐藏来源。
- Chrome 实际 PubMed 中文查询「他汀会增加新发糖尿病风险吗」返回 12 篇文献；数字来自测试当时 API，后续可能变化。
- 1440、1024、768、390、375、320px 及 844×390 横屏检查，无横向页面溢出。
- 实测摘要设置、舒适阅读、新检索清空筛选、引用定位、减少动态效果切换和 GSAP 缺失降级；无浏览器脚本错误。
- Taste 真实浏览器检查 0 FAIL；保留大标题和非等高的次要活动面板提示，原因是首屏任务与自然内容高度优先，不为空记录填充虚构内容。主视觉内部留白用于平衡搜索面板。
- 本轮没有修改后端检索、实验数据或模型，不将 UI 测试结果当作临床准确率验证。

本地截图位于 outputs/MedLit-全新首页.png、MedLit-全新结果页.png、MedLit-文献内查找.png、MedLit-全新手机结果.png；测量位于 outputs/redesign-final。
