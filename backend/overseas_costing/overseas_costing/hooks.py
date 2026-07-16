"""
中文用途：Frappe 应用钩子文件。

这里用于声明：
1. app 基本信息
2. 模块名称
3. 后续安装钩子
4. 预留页面、权限、补丁、文档类型前端资源等入口
"""

app_name = "overseas_costing"
app_title = "海外采购综合成本核算"
app_publisher = "Yuewei"
app_description = "海外采购综合成本核算模块后端骨架"
app_email = "dev@yuewei.local"
app_license = "MIT"

after_install = "overseas_costing.install.after_install"

fixtures = []

doctype_js = {}
doc_events = {}
