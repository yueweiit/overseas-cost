frappe.pages["overseas-cost-workbench"] = frappe.pages["overseas-cost-workbench"] || {};

function hideDeskChromeWhenReady(workbench) {
  workbench.hideDeskChrome();
  requestAnimationFrame(() => workbench.hideDeskChrome());
  window.setTimeout(() => {
    if ($(workbench.wrapper).is(":visible")) workbench.hideDeskChrome();
  }, 300);
}

function ensureDeskModuleSidebar(workbench) {
  const $nativeSidebar = $(
    ".body-sidebar-container, .desk-sidebar-container, .app-sidebar, .standard-sidebar"
  ).first();
  if ($nativeSidebar.length) {
    $nativeSidebar.css({ display: "", visibility: "visible", opacity: "1" });
    $("#ocw-erp-module-sidebar-fallback").remove();
    $("body").removeClass("ocw-has-erp-module-sidebar-fallback");
    return;
  }

  const fallbackHosts = new Set(["127.0.0.1", "localhost", "development.localhost"]);
  if (!fallbackHosts.has(window.location.hostname)) {
    $("#ocw-erp-module-sidebar-fallback").remove();
    $("body").removeClass("ocw-has-erp-module-sidebar-fallback");
    return;
  }

  if ($("#ocw-erp-module-sidebar-fallback").length) return;

  const modules = [
    { label: "组织", href: "/app/users", icon: "users" },
    { label: "会计", href: "/app/accounting", icon: "book-open" },
    { label: "资产", href: "/app/assets", icon: "asset" },
    { label: "采购", href: "/app/buying", icon: "shopping-cart" },
    { label: "生产", href: "/app/manufacturing", icon: "production" },
    { label: "项目", href: "/app/projects", icon: "folder" },
    { label: "质量", href: "/app/quality", icon: "check-circle" },
    { label: "销售", href: "/app/selling", icon: "sell" },
    { label: "库存", href: "/app/stock", icon: "stock" },
    { label: "委外", href: "/app/subcontracting-order", icon: "tool" },
    { label: "设置", href: "/app/system-settings", icon: "setting" },
    {
      label: "海外成本核算",
      href: "/app/overseas-cost-workbench",
      icon: "calculator",
      active: true,
    },
  ];
  const renderIcon = (name) =>
    frappe.utils && frappe.utils.icon
      ? frappe.utils.icon(name, "md")
      : `<span class="ocw-erp-module-icon-fallback">${name.slice(0, 1).toUpperCase()}</span>`;
  const $sidebar = $(
    `<aside id="ocw-erp-module-sidebar-fallback" aria-label="ERP 模块导航">
      <div class="ocw-erp-module-sidebar-items">
        ${modules
          .map(
            (item) => `
              <a class="ocw-erp-module-link${item.active ? " is-active" : ""}"
                 href="${item.href}" title="${item.label}" aria-label="${item.label}">
                <span class="ocw-erp-module-icon">${renderIcon(item.icon)}</span>
                <span class="ocw-erp-module-label">${item.label}</span>
              </a>
            `
          )
          .join("")}
      </div>
    </aside>`
  );
  $("body").append($sidebar).addClass("ocw-has-erp-module-sidebar-fallback");
  workbench.applyDeskLayout();
}

frappe.pages["overseas-cost-workbench"].on_page_load = function (wrapper) {
  const workbench = new OverseasCostWorkbench(wrapper);
  frappe.pages["overseas-cost-workbench"].workbench = workbench;
  workbench.init();
  ensureDeskModuleSidebar(workbench);
  hideDeskChromeWhenReady(workbench);
  // 离开工作台时恢复桌面外壳（侧栏 / 顶部标签栏 / 右侧栏），避免影响其它页面。
  $(wrapper).on("hide", function () {
    workbench.restoreDeskChrome();
  });
};

frappe.pages["overseas-cost-workbench"].on_page_show = function () {
  const workbench = frappe.pages["overseas-cost-workbench"].workbench;
  if (!workbench) return;
  ensureDeskModuleSidebar(workbench);
  hideDeskChromeWhenReady(workbench);
  workbench.applyDeskLayout();
  requestAnimationFrame(() => workbench.applyDeskLayout());
};

class OverseasCostWorkbench {
  constructor(wrapper) {
    this.wrapper = wrapper;
    this.page = null;
    this.$root = null;
    this.batches = [];
    this.visibleBatches = [];
    this.batchItems = {};
    this.batchColumns = [];
    this.expandedBatchNames = new Set();
    this.activeBatchName = "";
    this.drawerBatchName = "";
    this.drawerTab = "overview";
    this.focusedBatchName = "";
    this.batchClickTimer = null;
    this.exportPinnedBatchName = "";
    this.dataCheckBatchName = "";
    this.filters = {
      start_date: "",
      end_date: "",
      customs_no: "",
      waybill_no: "",
      material_code: "",
      product_name: "",
      import_name: "",
      hs_code: "",
      category: "",
      subsidiary_code: "",
      calculation_status: "",
      erp_status: "",
      transport_mode: "",
      business_type: "",
    };
    this.readonlyCalcFields = new Set(["goods_value_ratio", "freight_alloc_rmb", "freight_alloc_mxn", "total_logistics_mxn"]);
    this.specialOverrideFields = new Set(["weight_ratio", "alloc_price_mxn", "total_cost_rmb", "total_unit_rmb"]);
    this.selectOptions = {
      transport_mode: ["SEA", "AIR", "EXPRESS"],
      business_type: [
        { value: "SEA_STANDARD", label: "\u6d77\u8fd0\u6b63\u62a5\u6b63\u6e05" },
        { value: "SEA_DDP", label: "\u6d77\u8fd0 DDP\uff08\u53cc\u6e05\u5305\u7a0e\uff09" },
        { value: "AIR_DDP", label: "\u7a7a\u8fd0 DDP\uff08\u53cc\u6e05\u5305\u7a0e\uff09" },
        { value: "AIR_STANDARD", label: "\u6b63\u5e38\u7a7a\u8fd0" },
        { value: "EXPRESS", label: "\u5feb\u9012" },
      ],
      purchase_currency: ["RMB", "USD", "MXN"],
    };
    this.auditEvents = [];
    this.usageEvents = [];
    this.usageSummary = null;
    this.businessEntityOptions = [];
    this.businessEntityOptionsSignature = "";
    this.businessTypeOptions = [];
    this.erpQueueMode = false;
    this.workRole = "purchase";
    this.erpQueueStatus = "all";
    this.lastImportResult = null;
    this.lastRecalculateResult = null;
    this.lastImportedBatchNames = new Set();
    this.isOpeningDingtalk = false;
    this.isParsingManualDocuments = false;
    this.defaultRecentDays = 30;
    Object.assign(this.filters, this.getDefaultPullDateRange());
    this.moreFiltersOpen = false;
    this.erpFlowBlockState = null;
    this.childPriorityFields = this.loadChildPriorityFields();
    this.transportSidebarCollapsed = this.loadTransportSidebarState();
  }

  init() {
    this.resetDeskLayoutClasses();
    this.prepareWorkbenchContainer();
    this.page = frappe.ui.make_app_page({
      parent: this.wrapper,
      title: "海外采购综合成本核算",
      single_column: true,
    });
    this.applyDeskLayout();
    this.addActions();
    this.renderShell();
    this.bindEvents();
    this.loadBusinessEntityOptions();
    this.loadBatches();
    this.recordUsage("PAGE_VIEW", { remark: "进入海外采购综合成本核算工作台" });
  }

  prepareWorkbenchContainer() {
    // 清空 wrapper，再由 make_app_page 重建页面骨架。
    $(this.wrapper).empty();
  }

  // 保留 ERP 原生模块侧边栏，只隐藏会遮挡工作台的顶部标签栏和右侧栏。
  hideDeskChrome() {
    const targets = [
      $("#custom-filters-desk-tabs-bar"),
      $(".custom-filters-right-sidebar-container"),
    ];
    this._hiddenChrome = this._hiddenChrome || [];
    const trackedElements = this._hiddenChrome.map((item) => item.el[0]);
    const newlyVisibleTargets = targets
      .filter(($el) => $el.length && $el.is(":visible") && !trackedElements.includes($el[0]));
    this._hiddenChrome.push(
      ...newlyVisibleTargets
        .map(($el) => ({ el: $el, display: $el[0].style.display }))
    );
    this._hiddenChrome.forEach((item) => {
      item.el[0].style.display = "none";
    });
    console.info("[overseas-cost-workbench] 隐藏桌面外壳", {
      hidden: this._hiddenChrome.map((item) => item.el.attr("id") || item.el.attr("class")),
    });
  }

  // 离开工作台时恢复上面隐藏的元素，避免影响其它页面。
  restoreDeskChrome() {
    if (this._hiddenChrome && this._hiddenChrome.length) {
      this._hiddenChrome.forEach((item) => {
        item.el[0].style.display = item.display;
      });
      this._hiddenChrome = null;
    }
    this.resetDeskLayoutClasses();
  }

  resetDeskLayoutClasses() {
    $(".ocw-desk-fullwidth, .ocw-desk-wide-node, .ocw-desk-layout, .ocw-desk-section-wrapper, .ocw-desk-main").removeClass(
      "ocw-desk-fullwidth ocw-desk-wide-node ocw-desk-layout ocw-desk-section-wrapper ocw-desk-main"
    );
  }

  applyDeskLayout() {
    this.resetDeskLayoutClasses();
    const $wrapper = $(this.wrapper);
    const $mainSection = $(this.page.main);

    $wrapper.addClass("ocw-desk-fullwidth");
    $mainSection
      .addClass("ocw-desk-main")
      .parents(
        ".container, .page-body, .page-content, .page-wrapper, .layout-main, .layout-main-section, .layout-main-section-wrapper"
      )
      .addClass("ocw-desk-wide-node");

    $mainSection.closest(".page-body").addClass("full-width");
    $mainSection.closest(".layout-main").addClass("ocw-desk-layout");
    $mainSection.closest(".layout-main-section-wrapper").addClass("ocw-desk-section-wrapper");
  }

  addActions() {
    // 操作入口保留在工作台内部，避免 Frappe 顶部 Actions 与页面按钮重复。
    if (this.page.clear_primary_action) this.page.clear_primary_action();
    if (this.page.clear_actions_menu) this.page.clear_actions_menu();
  }

  renderShell() {
    this.$root = $(`
      <div class="ocw-page">
        <div class="ocw-shell">
          <aside class="ocw-sidebar">
            <div class="ocw-brand">
              <div class="ocw-logo">YW</div>
              <div>
                <p>Mexico Ocean Costing</p>
                <h1>海外采购综合成本核算</h1>
              </div>
            </div>
            <section class="ocw-logistics-panel">
              <div class="ocw-logistics-panel-head">
                <span>业务类型</span>
                <button
                  class="ocw-sidebar-toggle"
                  type="button"
                  data-action="toggle-transport-sidebar"
                  aria-expanded="true"
                  aria-label="收起业务类型栏"
                  title="收起业务类型栏"
                >
                  <span class="ocw-sidebar-toggle-icon" aria-hidden="true"></span>
                </button>
                <button class="ocw-text-btn" type="button" data-action="set-transport-filter" data-transport-mode="">全部</button>
              </div>
              <div class="ocw-logistics-list" data-area="transport-workbench"></div>
              <div class="ocw-sidebar-scope-note">
                <span>默认最近 30 天</span>
                <span>可按审批发起时间筛选</span>
              </div>
            </section>
          </aside>

          <main class="ocw-main">
            <section class="ocw-workbench-card">
              <div class="ocw-workbench-head">
                <div>
                  <h3>SKU 成本分摊明细 / 物料详情</h3>
                </div>
                <div class="ocw-head-actions">
                  <button class="ocw-success-btn ocw-mini-btn" data-action="export-current">导出当前全部批次结果</button>
                  <button class="ocw-warning-btn ocw-mini-btn" data-action="file-parse">凭证对比</button>
                  <button class="ocw-outline-btn ocw-mini-btn" data-action="preview-categories">商品归类</button>
                  <button class="ocw-outline-btn ocw-mini-btn" data-action="pull-oa-logistics">钉钉拉取</button>
                  <button class="ocw-outline-btn ocw-mini-btn" data-action="open-import">Excel 导入</button>
                  <button class="ocw-primary-btn ocw-mini-btn" data-action="add-batch">+ 添加报关运单</button>
                </div>
              </div>

              <div class="ocw-query-toolbar">
                <div class="ocw-filter-grid">
                  <label class="ocw-toolbar-field ocw-toolbar-field-date">
                    <span>开始日期</span>
                    <input data-filter="start_date" class="form-control" type="date" value="${this.escape(this.filters.start_date)}" />
                  </label>
                  <label class="ocw-toolbar-field ocw-toolbar-field-date">
                    <span>结束日期</span>
                    <input data-filter="end_date" class="form-control" type="date" value="${this.escape(this.filters.end_date)}" />
                  </label>
                  <label class="ocw-toolbar-field ocw-toolbar-field-entity">
                    <span>业务主体</span>
                    <select data-filter="subsidiary_code" class="form-control">
                      <option value="">全部业务主体</option>
                    </select>
                  </label>
                  <label class="ocw-toolbar-field ocw-toolbar-field-erp">
                    <span>ERP 状态</span>
                    <select data-filter="erp_status" class="form-control">
                      <option value="">全部</option>
                      <option value="not_started">未开始</option>
                      <option value="pending">待接口推送</option>
                      <option value="success">推送成功</option>
                      <option value="failed">推送失败</option>
                    </select>
                  </label>
                  <div class="ocw-filter-actions">
                    <button class="ocw-primary-btn ocw-mini-btn" data-action="apply-filters">查询</button>
                    <button class="ocw-outline-btn ocw-mini-btn" data-action="clear-filters">重置</button>
                  </div>
                </div>
                <div class="ocw-query-footer">
                  <div class="ocw-search-result" data-area="search-result">查询后会锁定当前结果；回到全部批次请点击“重置”</div>
                  <button class="ocw-text-btn" type="button" data-action="toggle-more-filters" aria-expanded="false">更多筛选 +</button>
                </div>
                <div class="ocw-filter-chips" data-area="filter-chips" aria-live="polite"></div>
                <div class="ocw-more-filter-grid" data-area="more-filters" hidden>
                  <label class="ocw-toolbar-field">
                    <span>核算状态</span>
                    <select data-filter="calculation_status" class="form-control">
                      <option value="">全部</option>
                      <option value="草稿">草稿</option>
                      <option value="已导入">已导入</option>
                      <option value="待重算">待重算</option>
                      <option value="已试算">已试算</option>
                      <option value="已确认">已确认</option>
                    </select>
                  </label>
                  <label class="ocw-toolbar-field">
                    <span>批次/报关单号/钉钉审批编号</span>
                    <input data-filter="customs_no" class="form-control" type="search" placeholder="请输入批次号、报关单号或钉钉审批编号" />
                  </label>
                  <label class="ocw-toolbar-field">
                    <span>物料编码</span>
                    <input data-filter="material_code" class="form-control" type="search" placeholder="请输入物料编码" />
                  </label>
                  <label class="ocw-toolbar-field">
                    <span>物料名称</span>
                    <input data-filter="product_name" class="form-control" type="search" placeholder="请输入物料名称" />
                  </label>
                  <label class="ocw-toolbar-field">
                    <span>海关进口名称</span>
                    <input data-filter="import_name" class="form-control" type="search" placeholder="请输入海关进口名称" />
                  </label>
                  <label class="ocw-toolbar-field">
                    <span>海关分类编码</span>
                    <input data-filter="hs_code" class="form-control" type="search" placeholder="请输入海关分类编码" />
                  </label>
                  <label class="ocw-toolbar-field">
                    <span>大类</span>
                    <input data-filter="category" class="form-control" type="search" placeholder="请输入大类" />
                  </label>
                </div>
              </div>

                <div class="ocw-table-toolbar">
                  <div class="ocw-table-toolbar-left">
                    <button class="ocw-outline-btn ocw-mini-btn" data-action="clear-batch-focus" hidden>返回全部批次</button>
                    <button class="ocw-outline-btn ocw-mini-btn" data-action="expand-current">+ 全部展开</button>
                    <button class="ocw-outline-btn ocw-mini-btn" data-action="collapse-current">- 全部收起</button>
                    <div class="ocw-role-switch" aria-label="岗位工作视图">
                      <button class="active" type="button" data-action="set-work-role" data-role="purchase">采购</button>
                      <button type="button" data-action="set-work-role" data-role="finance">财务</button>
                    </div>
                    <strong class="ocw-role-title" data-area="table-title">采购待补资料</strong>
                    <span data-area="table-count"></span>
                  </div>
                  <div class="ocw-table-hint">
                    <span data-area="role-description">采购视图：处理数据不完整批次，补齐资料</span>
                    <span>单击批次可选中并锁定；双击批次打开详情侧边栏</span>
                  </div>
                  <div class="ocw-table-actions">
                    <button class="ocw-outline-btn ocw-mini-btn" type="button" data-action="configure-sku-columns">SKU重点字段</button>
                    <div class="ocw-view-switch">
                      <button class="active" type="button" data-action="set-main-view" data-view="cost">成本列表</button>
                      <button type="button" data-action="set-main-view" data-view="erp_queue">ERP 队列</button>
                  </div>
                </div>
              </div>
              <div class="ocw-hierarchy-wrap" data-area="table"></div>
            </section>

            <div class="ocw-batch-drawer-mask" data-area="batch-drawer-mask" data-action="close-batch-drawer"></div>
            <aside class="ocw-batch-drawer" data-area="batch-drawer" aria-hidden="true">
              <div class="ocw-batch-drawer-head">
                <div>
                  <span>批次详情</span>
                  <strong data-area="batch-drawer-title">批次详情（字段修改请在明细区操作）</strong>
                </div>
                <div class="ocw-batch-drawer-head-actions">
                  <button class="ocw-outline-btn ocw-mini-btn" data-action="export-drawer-batch">导出当前批次</button>
                  <button class="ocw-outline-btn ocw-mini-btn" data-action="open-batch-drawer-dingtalk">钉钉原单</button>
                  <button class="ocw-outline-btn ocw-mini-btn" data-action="open-batch-drawer-recalculate">重新试算</button>
                  <button class="ocw-icon-btn" data-action="close-batch-drawer" aria-label="关闭">×</button>
                </div>
              </div>
              <div class="ocw-batch-drawer-tabs">
                <button class="ocw-batch-drawer-tab active" data-action="switch-batch-drawer-tab" data-tab="overview">概览</button>
                <button class="ocw-batch-drawer-tab" data-action="switch-batch-drawer-tab" data-tab="items">物料明细</button>
                <button class="ocw-batch-drawer-tab" data-action="switch-batch-drawer-tab" data-tab="allocation">AI 分摊</button>
                <button class="ocw-batch-drawer-tab" data-action="switch-batch-drawer-tab" data-tab="audit">修改记录</button>
                <button class="ocw-batch-drawer-tab" data-action="switch-batch-drawer-tab" data-tab="usage">使用记录</button>
              </div>
              <div class="ocw-batch-drawer-body" data-area="batch-drawer-body"></div>
            </aside>

          </main>
        </div>
      </div>
    `);
    $(this.page.main).empty().append(this.$root);
    this.applyDeskLayout();
    this.setTransportSidebarCollapsed(this.transportSidebarCollapsed, false);
    this.renderEmpty();
    this.renderAuditList();
    this.renderDiffPanel();
  }

  loadTransportSidebarState() {
    try {
      return window.localStorage.getItem("overseas-costing:transport-sidebar-collapsed") === "1";
    } catch (error) {
      return false;
    }
  }

  setTransportSidebarCollapsed(collapsed, persist = true) {
    this.transportSidebarCollapsed = Boolean(collapsed);
    if (persist) {
      try {
        window.localStorage.setItem(
          "overseas-costing:transport-sidebar-collapsed",
          this.transportSidebarCollapsed ? "1" : "0"
        );
      } catch (error) {
        // 浏览器禁用本地存储时仍保留本次页面状态。
      }
    }
    if (!this.$root) return;
    const $shell = this.$root.find(".ocw-shell");
    const $toggle = this.$root.find("[data-action='toggle-transport-sidebar']");
    $shell.toggleClass("is-transport-sidebar-collapsed", this.transportSidebarCollapsed);
    $toggle.attr({
      "aria-expanded": String(!this.transportSidebarCollapsed),
      "aria-label": this.transportSidebarCollapsed ? "展开业务类型栏" : "收起业务类型栏",
      title: this.transportSidebarCollapsed ? "展开业务类型栏" : "收起业务类型栏",
    });
  }

  toggleTransportSidebar() {
    this.setTransportSidebarCollapsed(!this.transportSidebarCollapsed);
  }

  bindEvents() {
    this.$root.on("click", "[data-batch-name]", (event) => {
      if ($(event.currentTarget).hasClass("ocw-parent-row")) return;
      const batchName = $(event.currentTarget).attr("data-batch-name");
      if (batchName) {
        this.activeBatchName = batchName;
        this.exportPinnedBatchName = batchName;
        this.renderDiffPanel();
        this.updateRecalculateAction();
        const batch = this.findBatch(batchName);
        this.loadAuditLogs(batchName, batch ? batch.current_version : null).catch((error) => this.showError(error));
      }
    });

    this.$root.on("click", "[data-action='reload-batches']", () => this.loadBatches());
    this.$root.on("click", "[data-action='set-work-role']", (event) => this.setWorkRole($(event.currentTarget).attr("data-role")));
    this.$root.on("click", "[data-action='set-main-view']", (event) => this.setMainView($(event.currentTarget).attr("data-view")));
    this.$root.on("click", "[data-action='set-erp-queue-status']", (event) => this.setErpQueueStatus($(event.currentTarget).attr("data-status")));
    this.$root.on("click", "[data-action='apply-filters']", () => this.applyFilters());
    this.$root.on("click", "[data-action='clear-filters']", () => this.clearFilters());
    this.$root.on("click", "[data-action='toggle-more-filters']", () => this.toggleMoreFilters());
    this.$root.on("click", "[data-action='toggle-transport-sidebar']", () => this.toggleTransportSidebar());
    this.$root.on("click", "[data-action='remove-filter']", (event) => {
      this.removeFilter($(event.currentTarget).attr("data-filter"));
    });
    this.$root.on("click", "[data-action='configure-sku-columns']", () => this.openChildColumnPreferenceDialog());
    this.$root.on("click", "[data-action='set-transport-filter']", (event) =>
      this.setTransportFilter($(event.currentTarget).attr("data-transport-mode")).catch((error) => this.showError(error))
    );
    this.$root.on("click", "[data-action='recalculate']", (event) => this.recalculate($(event.currentTarget).attr("data-batch-name")));
    this.$root.on("click", "[data-action='open-import']", () => this.openImportDialog());
    this.$root.on("click", "[data-action='pull-oa-logistics']", () => this.openOaLogisticsPullDialog());
    this.$root.on("change", "[data-role='data-check-batch-select']", (event) => {
      const batchName = String($(event.currentTarget).val() || "");
      const batch = this.findBatch(batchName);
      if (!batch) return;
      this.dataCheckBatchName = batch.name;
      this.loadBatchItems(batch.name, batch.current_version)
        .then(() => this.renderDiffPanel())
        .catch((error) => this.showError(error));
    });
    this.$root.on("click", "[data-action='preview-categories']", () => this.openCategoryPreviewDialog());
    this.$root.on("click", "[data-action='file-parse']", () => this.openFileParseDialog());
    this.$root.on("click", "[data-action='export-current']", () => this.exportCurrentResult().catch((error) => this.showError(error)));
    this.$root.on("click", "[data-action='open-dingtalk']", (event) => this.openDingtalkOrder($(event.currentTarget).attr("data-batch-name")));
    this.$root.on("click", "[data-action='preview-purchase']", (event) => this.openPurchasePreviewDialog($(event.currentTarget).attr("data-batch-name")));
    this.$root.on("click", "[data-action='oa-attachments']", (event) => this.openOaAttachmentDialog($(event.currentTarget).attr("data-batch-name")));
    this.$root.on("click", "[data-action='manual-logistics-quote']", (event) => this.openLogisticsQuoteDialog($(event.currentTarget).attr("data-batch-name")));
    this.$root.on("click", "[data-action='source-center']", (event) => this.openSourceCenterDialog($(event.currentTarget).attr("data-batch-name")));
    this.$root.on("click", "[data-action='row-more']", (event) => this.openRowMoreDialog($(event.currentTarget).attr("data-batch-name")));
    this.$root.on("click", ".ocw-parent-row", (event) => {
      if ($(event.target).closest("button, input, select, textarea, a").length) return;
      const batchName = $(event.currentTarget).attr("data-batch-name");
      window.clearTimeout(this.batchClickTimer);
      this.batchClickTimer = window.setTimeout(() => {
        this.focusBatch(batchName).catch((error) => this.showError(error));
      }, 220);
    });
    this.$root.on("dblclick", ".ocw-parent-row", (event) => {
      if ($(event.target).closest("button, input, select, textarea, a").length) return;
      window.clearTimeout(this.batchClickTimer);
      this.batchClickTimer = null;
      this.openBatchDrawer($(event.currentTarget).attr("data-batch-name"));
    });
    this.$root.on("click", "[data-action='clear-batch-focus']", () => this.clearBatchFocus());
    this.$root.on("click", "[data-action='close-batch-drawer']", () => this.closeBatchDrawer());
    this.$root.on("click", "[data-action='switch-batch-drawer-tab']", (event) =>
      this.switchBatchDrawerTab($(event.currentTarget).attr("data-tab"))
    );
    this.$root.on("click", "[data-action='save-profit-inputs']", () => this.saveProfitInputs());
    this.$root.on("input change", "[data-profit-input]", () => this.updateProfitDrawerPreview());
    this.$root.on("click", "[data-action='export-drawer-batch']", () => this.exportDrawerBatch().catch((error) => this.showError(error)));
    this.$root.on("click", "[data-action='open-batch-drawer-dingtalk']", () => this.openDingtalkOrder(this.drawerBatchName));
    this.$root.on("click", "[data-action='open-batch-drawer-recalculate']", () => this.recalculate(this.drawerBatchName));
    this.$root.on("click", "[data-action='confirm-calculation-result']", () => this.confirmCalculationResult(this.drawerBatchName));
    this.$root.on("click", "[data-action='preview-erp-payload']", () => this.previewErpPayload(this.drawerBatchName));
    this.$root.on("click", "[data-action='writeback-to-erp']", () => this.writebackToErp(this.drawerBatchName));
    this.$root.on("click", "[data-action='queue-preview-erp']", (event) => {
      const batchName = $(event.currentTarget).attr("data-batch-name");
      const batch = this.findBatch(batchName);
      if (!batch) return;
      const openPreview = async () => {
        if (!this.$root.find("[data-area='batch-drawer']").hasClass("is-open")) {
          await this.openBatchDrawer(batch.name, { updateUrl: false });
        }
        await this.previewErpPayload(batch.name);
      };
      openPreview().catch((error) => this.showError(error));
    });
    this.$root.on("click", "[data-action='queue-writeback-erp']", (event) => this.writebackToErp($(event.currentTarget).attr("data-batch-name")));
    this.$root.on("click", "[data-action='queue-open-batch']", (event) => this.openBatchDrawer($(event.currentTarget).attr("data-batch-name")));
    this.$root.on("click", "[data-action='gap-repull-dingtalk']", (event) => this.repullGapDingtalk($(event.currentTarget).attr("data-batch-name")));
    this.$root.on("click", "[data-action='gap-confirm-actual-qty']", (event) =>
      this.confirmActualQtyFromQuantity($(event.currentTarget).attr("data-batch-name")).catch((error) => this.showError(error))
    );
    this.$root.on("click", "[data-action='gap-open-fee-pool']", (event) => {
      const $button = $(event.currentTarget);
      this.openFeePoolGapDialog($button.attr("data-batch-name"), {
        fieldname: $button.attr("data-gap-fieldname"),
        label: $button.attr("data-gap-label"),
      });
    });
    this.$root.on("click", "[data-action='gap-open-source-center']", (event) => {
      const $button = $(event.currentTarget);
      this.openSourceCenterDialog($button.attr("data-batch-name"), {
        fieldname: $button.attr("data-gap-fieldname"),
        label: $button.attr("data-gap-label"),
      });
    });
    this.$root.on("click", "[data-action='gap-confirm-zero-fee']", (event) => {
      const $button = $(event.currentTarget);
      this.confirmZeroFeeGap($button.attr("data-batch-name"), {
        fieldname: $button.attr("data-gap-fieldname"),
        label: $button.attr("data-gap-label"),
      }).catch((error) => this.showError(error));
    });
    this.$root.on("click", "[data-action='gap-open-item-edit']", (event) =>
      this.openGapItemEdit(
        $(event.currentTarget).attr("data-batch-name"),
        $(event.currentTarget).attr("data-item-name"),
        $(event.currentTarget).attr("data-fieldname")
      ).catch((error) => this.showError(error))
    );
    this.$root.on("click", "[data-action='gap-recalculate']", (event) => this.recalculate($(event.currentTarget).attr("data-batch-name")));
    this.$root.on("click", "[data-action='open-generic-link']", (event) => this.openDingtalkLink($(event.currentTarget).attr("data-open-url")));
    this.$root.on("click", "[data-action='add-batch']", () => this.openAddBatchDialog());
    this.$root.on("click", "[data-action='toggle-batch']", (event) => this.toggleBatch($(event.currentTarget).attr("data-batch-name")));
    this.$root.on("click", "[data-action='expand-current']", () => this.setAllExpanded(true));
    this.$root.on("click", "[data-action='collapse-current']", () => this.setAllExpanded(false));
    this.$root.on("click", "[data-action='refresh-batch']", (event) => this.refreshBatch($(event.currentTarget).attr("data-batch-name")));
    this.$root.on("click", "[data-action='delete-batch']", (event) => this.confirmDeleteBatch($(event.currentTarget).attr("data-batch-name")));
    this.$root.on("click", "[data-action='add-material']", (event) => this.openAddMaterialDialog($(event.currentTarget).attr("data-batch-name")));
    this.$root.on("click", "[data-action='delete-material']", (event) => {
      this.confirmDeleteMaterial(
        $(event.currentTarget).attr("data-batch-name"),
        $(event.currentTarget).attr("data-item-name"),
        $(event.currentTarget).attr("data-item-label")
      );
    });
    this.$root.on("click", "[data-editable-cell='1']", (event) => {
      if ($(event.target).closest(".ocw-cell-editor").length) return;
      const $cell = $(event.currentTarget);
      const autoOpenSelect = Boolean(this.selectOptions[$cell.attr("data-fieldname")]);
      this.startCellEdit($cell, event, autoOpenSelect);
    });
    this.$root.on("keydown", ".ocw-cell-editor", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        event.stopImmediatePropagation();
        this.commitCellEdit($(event.currentTarget).closest("td"));
      }
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopImmediatePropagation();
        this.cancelCellEdit($(event.currentTarget).closest("td"));
      }
    });
    this.$root.on("blur", ".ocw-cell-editor", (event) => {
      const $cell = $(event.currentTarget).closest("td");
      window.setTimeout(() => this.commitCellEdit($cell), 0);
    });
    this.$root.on("change", "select.ocw-cell-editor", (event) => this.commitCellEdit($(event.currentTarget).closest("td")));

    this.$root.on("keydown", "input", (event) => {
      if ($(event.currentTarget).hasClass("ocw-cell-editor")) return;
      if (event.key === "Enter") this.applyFilters();
    });

    this.$root.on("input change", "[data-filter]", (event) => {
      const field = $(event.currentTarget).attr("data-filter");
      this.filters[field] = $(event.currentTarget).val();
      this.renderFilterChips();
    });
    $(window)
      .off("popstate.ocwBatchFocus")
      .on("popstate.ocwBatchFocus", () => this.applyBatchFocusFromUrl().catch((error) => this.showError(error)));
  }

  async call(method, args = {}, freeze = false) {
    const response = await frappe.call({ method, args, freeze });
    return response.message || {};
  }

  async loadBatches() {
    this.setTableLoading();
    try {
      const result = await this.call("overseas_costing.api.batch.get_batch_list", this.getBatchListQueryArgs());
      this.batches = this.sortBatchesNewestFirst(result.items || []);
      this.visibleBatches = this.batches.slice();
      this.expandedBatchNames.clear();
      await this.prefetchBatchItems(this.visibleBatches);
      this.visibleBatches = this.filterBatches();
      const urlBatch = this.restoreBatchFocusStateFromUrl();
      this.renderTransportWorkbench();
      if (this.batches.length) {
        this.syncActiveSelectionWithVisible();
        const activeBatch = urlBatch || this.getVisibleActiveBatch();
        if (activeBatch) {
          await this.loadAuditLogs(activeBatch.name, activeBatch.current_version);
        } else {
          this.auditEvents = [];
          this.renderAuditList();
        }
        this.renderTable();
        this.updateSearchResult();
        this.updateRecalculateAction();
        if (urlBatch && this.getBatchViewFromUrl() === "drawer") {
          await this.openBatchDrawer(urlBatch.name, { updateUrl: false });
        }
      } else {
        this.renderEmpty();
      }
    } catch (error) {
      this.showError(error);
    }
  }

  async prefetchBatchItems(batches) {
    const targets = batches.filter((batch) => batch && batch.name && !this.batchItems[batch.name]);
    await Promise.all(targets.map((batch) => this.loadBatchItems(batch.name, batch.current_version)));
  }

  async loadBatchItems(batchName, versionName = null, force = false) {
    if (!batchName) return { columns: this.batchColumns, items: [] };
    if (!force && this.batchItems[batchName]) {
      return { columns: this.batchColumns, items: this.batchItems[batchName] };
    }
    const result = await this.call("overseas_costing.api.batch.get_batch_items", {
      batch_name: batchName,
      version_name: versionName,
      // 报关单号和运单号属于整票筛选条件。命中批次后仍加载完整物料，
      // 避免单号只在批次头时出现父级命中、明细为空。
      customs_no: "",
      waybill_no: "",
      material_code: this.filters.material_code,
      product_name: this.filters.product_name,
      import_name: this.filters.import_name,
      hs_code: this.filters.hs_code,
      category: this.filters.category,
    });
    this.batchColumns = result.columns || this.batchColumns || [];
    this.batchItems[batchName] = result.items || [];
    return { columns: this.batchColumns, items: this.batchItems[batchName] };
  }

  async loadAuditLogs(batchName = null, versionName = null) {
    const batch = batchName ? this.findBatch(batchName) : this.getActiveBatch();
    if (!batch) {
      this.auditEvents = [];
      this.renderAuditList();
      return;
    }
    const result = await this.call("overseas_costing.api.batch.get_audit_logs", {
      batch_name: batch.name,
      version_name: versionName || batch.current_version || null,
      limit: 80,
    });
    if (!result.ok) throw new Error(result.message || "修改记录加载失败");
    this.auditEvents = (result.items || []).map((row) => this.mapAuditRow(row, batch));
    this.renderAuditList();
  }

  recordUsage(actionType, options = {}) {
    const batch = options.batchName ? this.findBatch(options.batchName) : options.batch || null;
    const payload = {
      action_type: actionType || "OTHER",
      batch_name: options.batchName || (batch && batch.name) || "",
      version_name: options.versionName || (batch && batch.current_version) || "",
      status: options.status || "Success",
      remark: options.remark || "",
      route: window.location.hash || window.location.pathname || "",
      extra_json: JSON.stringify(options.extra || {}),
    };
    frappe
      .call({
        method: "overseas_costing.api.usage.record_usage",
        args: payload,
      })
      .catch((error) => {
        console.warn("[overseas-cost-workbench] 使用记录写入失败", error);
      });
  }

  async loadUsageLogs(batchName = null) {
    const batch = batchName ? this.findBatch(batchName) : this.getActiveBatch();
    if (!batch) {
      this.usageEvents = [];
      this.usageSummary = null;
      if (this.drawerTab === "usage") this.renderBatchDrawer();
      return;
    }
    const [logs, summary] = await Promise.all([
      this.call("overseas_costing.api.usage.get_usage_logs", {
        batch_name: batch.name,
        limit: 80,
      }),
      this.call("overseas_costing.api.usage.get_usage_summary", {
        days: 30,
        limit: 12,
      }),
    ]);
    if (!logs.ok) throw new Error(logs.message || "使用记录加载失败");
    this.usageEvents = (logs.items || []).map((row) => this.mapUsageRow(row, batch));
    this.usageSummary = summary && summary.ok ? summary : null;
    if (this.drawerTab === "usage") this.renderBatchDrawer();
  }

  async applyFilters() {
    this.setTableLoading();
    try {
      this.focusedBatchName = "";
      this.closeBatchDrawer({ updateUrl: false });
      this.updateBatchUrl("", { replace: true });
      this.exportPinnedBatchName = "";
      this.batchItems = {};
      await this.reloadBatchesForServerSearch(true);
      if (!this.batches.length) {
        this.renderEmpty();
        return;
      }
      await this.prefetchBatchItems(this.batches);
      this.visibleBatches = this.filterBatches();
      this.renderTransportWorkbench();
      this.syncActiveSelectionWithVisible();
      if (this.hasActiveFilters()) {
        this.expandedBatchNames = new Set(this.visibleBatches.map((batch) => batch.name));
      }
      this.renderTable();
      this.updateSearchResult();
    } catch (error) {
      this.showError(error);
    }
  }

  clearFilters() {
    this.resetFilterValues();
    this.moreFiltersOpen = false;
    this.$root.find("[data-area='more-filters']").prop("hidden", true);
    this.$root.find("[data-action='toggle-more-filters']").attr("aria-expanded", "false").text("更多筛选 +");
    this.resetBatchScopeState();
    this.batchItems = {};
    this.loadBatches();
  }

  async loadBusinessEntityOptions() {
    try {
      const result = await this.call("overseas_costing.api.batch.get_batch_filter_options");
      this.businessEntityOptions = Array.isArray(result.items) ? result.items : [];
      this.businessTypeOptions = Array.isArray(result.business_types) && result.business_types.length
        ? result.business_types
        : this.selectOptions.business_type;
      this.renderBusinessEntityFilter();
      this.renderBusinessTypeFilter();
    } catch (error) {
      console.warn("[overseas-cost-workbench] 业务主体筛选选项加载失败", error);
    }
  }

  resetBatchScopeState() {
    this.focusedBatchName = "";
    this.exportPinnedBatchName = "";
    this.dataCheckBatchName = "";
    this.erpFlowBlockState = null;
    this.closeBatchDrawer({ updateUrl: false });
    this.updateBatchUrl("", { replace: true, view: "" });
  }

  async setTransportFilter(mode = "") {
    this.filters.business_type = String(mode || "").trim().toUpperCase();
    this.filters.transport_mode = "";
    this.resetBatchScopeState();
    if (!this.batches.length) {
      await this.loadBatches();
      return;
    }
    await this.prefetchBatchItems(this.batches);
    this.visibleBatches = this.filterBatches();
    this.syncActiveSelectionWithVisible();
    if (!this.visibleBatches.length) {
      this.auditEvents = [];
      this.renderAuditList();
    } else {
      const activeBatch = this.getVisibleActiveBatch();
      if (activeBatch) await this.loadAuditLogs(activeBatch.name, activeBatch.current_version);
    }
    this.renderTransportWorkbench();
    this.renderTable();
    this.updateSearchResult();
  }

  syncActiveSelectionWithVisible() {
    if (!this.visibleBatches.length) {
      this.activeBatchName = "";
      this.focusedBatchName = "";
      this.exportPinnedBatchName = "";
      this.dataCheckBatchName = "";
      return;
    }
    if (this.focusedBatchName && !this.visibleBatches.some((batch) => batch.name === this.focusedBatchName)) {
      this.focusedBatchName = "";
    }
    if (!this.visibleBatches.some((batch) => batch.name === this.activeBatchName)) {
      this.activeBatchName = this.visibleBatches[0].name;
    }
    if (this.exportPinnedBatchName && !this.visibleBatches.some((batch) => batch.name === this.exportPinnedBatchName)) {
      this.exportPinnedBatchName = "";
    }
    if (!this.visibleBatches.some((batch) => batch.name === this.dataCheckBatchName)) {
      this.dataCheckBatchName = this.activeBatchName;
    }
  }

  getServerSearchKeyword() {
    return [
      this.filters.customs_no,
      this.filters.waybill_no,
      this.filters.material_code,
      this.filters.product_name,
      this.filters.import_name,
      this.filters.hs_code,
      this.filters.category,
    ]
      .map((value) => String(value || "").trim())
      .find(Boolean) || "";
  }

  async reloadBatchesForServerSearch(force = false) {
    const keyword = this.getServerSearchKeyword();
    if (!keyword && !force) return false;
    const result = await this.call("overseas_costing.api.batch.get_batch_list", this.getBatchListQueryArgs(keyword));
    this.batches = this.sortBatchesNewestFirst(result.items || []);
    this.visibleBatches = this.batches.slice();
    return true;
  }

  resetFilterValues() {
    Object.keys(this.filters).forEach((key) => {
      this.filters[key] = "";
      this.$root.find(`[data-filter='${key}']`).val("");
    });
    Object.assign(this.filters, this.getDefaultPullDateRange());
    this.$root.find("[data-filter='start_date']").val(this.filters.start_date);
    this.$root.find("[data-filter='end_date']").val(this.filters.end_date);
    this.renderFilterChips();
  }

  getBatchListQueryArgs(keyword = "") {
    const dateRangeIsDefault = this.hasDefaultDateRange();
    return {
      transport_mode: "",
      business_type: this.filters.business_type || "",
      recent_days: this.defaultRecentDays,
      keyword,
      include_history: dateRangeIsDefault ? 1 : 0,
      start_date: dateRangeIsDefault ? "" : this.filters.start_date,
      end_date: dateRangeIsDefault ? "" : this.filters.end_date,
    };
  }

  hasDefaultDateRange() {
    const defaults = this.getDefaultPullDateRange();
    return this.filters.start_date === defaults.start_date && this.filters.end_date === defaults.end_date;
  }

  filterFieldLabels() {
    return {
      start_date: "开始日期",
      end_date: "结束日期",
      customs_no: "批次/报关单号/钉钉审批编号",
      material_code: "物料编码",
      product_name: "物料名称",
      import_name: "海关进口名称",
      hs_code: "海关分类编码",
      category: "大类",
      subsidiary_code: "业务主体",
      calculation_status: "核算状态",
      erp_status: "ERP 状态",
      transport_mode: "运输方式",
      business_type: "业务类型",
    };
  }

  filterChipEntries() {
    const labels = this.filterFieldLabels();
    const entries = [];
    const defaults = this.getDefaultPullDateRange();
    if (this.filters.start_date !== defaults.start_date || this.filters.end_date !== defaults.end_date) {
      entries.push({ field: "start_date", label: labels.start_date, value: this.filters.start_date || "未填" });
      entries.push({ field: "end_date", label: labels.end_date, value: this.filters.end_date || "未填" });
    }
    Object.keys(labels)
      .filter((field) => !["start_date", "end_date"].includes(field))
      .forEach((field) => {
        const value = String(this.filters[field] || "").trim();
        if (!value) return;
        entries.push({ field, label: labels[field], value: this.filterChipValue(field, value) });
      });
    return entries;
  }

  filterChipValue(field, value) {
    if (field === "business_type") return this.businessTypeCompactLabel(value);
    if (field === "erp_status") {
      return {
        not_started: "未开始",
        pending: "待接口推送",
        success: "推送成功",
        failed: "推送失败",
      }[value] || value;
    }
    if (field === "transport_mode") return this.transportLabel(value);
    return value;
  }

  renderFilterChips() {
    const $chips = this.$root && this.$root.find("[data-area='filter-chips']");
    if (!$chips || !$chips.length) return;
    const entries = this.filterChipEntries();
    if (!entries.length) {
      $chips.empty().prop("hidden", true);
      return;
    }
    $chips
      .prop("hidden", false)
      .html(entries.map((entry) => `
        <span class="ocw-filter-chip">
          <span class="ocw-filter-chip-label">${this.escape(entry.label)}：${this.escape(entry.value)}</span>
          <button type="button" class="ocw-filter-chip-remove" data-action="remove-filter" data-filter="${this.escape(entry.field)}" aria-label="移除${this.escape(entry.label)}">×</button>
        </span>
      `).join(""));
  }

  async removeFilter(field) {
    if (!field || !(field in this.filters)) return;
    if (field === "start_date" || field === "end_date") {
      Object.assign(this.filters, this.getDefaultPullDateRange());
      this.$root.find("[data-filter='start_date']").val(this.filters.start_date);
      this.$root.find("[data-filter='end_date']").val(this.filters.end_date);
    } else {
      this.filters[field] = "";
      this.$root.find(`[data-filter='${field}']`).val("");
    }
    this.renderFilterChips();
    await this.applyFilters();
  }

  toggleMoreFilters() {
    this.moreFiltersOpen = !this.moreFiltersOpen;
    const $button = this.$root.find("[data-action='toggle-more-filters']");
    this.$root.find("[data-area='more-filters']").prop("hidden", !this.moreFiltersOpen);
    $button.attr("aria-expanded", this.moreFiltersOpen ? "true" : "false").text(this.moreFiltersOpen ? "收起筛选 -" : "更多筛选 +");
  }

  childPriorityStorageKey() {
    return "overseas-cost-workbench:sku-priority-fields";
  }

  normalizeChildPriorityFields(fields, columns = this.batchColumns) {
    const selected = Array.isArray(fields) ? fields.filter((field) => typeof field === "string" && field) : [];
    const unique = [...new Set(selected)];
    if (!columns || !columns.length) return unique;
    const allowed = new Set(columns.map((column) => column.fieldname));
    return unique.filter((field) => allowed.has(field));
  }

  loadChildPriorityFields() {
    try {
      return this.normalizeChildPriorityFields(JSON.parse(window.localStorage.getItem(this.childPriorityStorageKey()) || "[]"));
    } catch (error) {
      return [];
    }
  }

  saveChildPriorityFields(fields) {
    this.childPriorityFields = this.normalizeChildPriorityFields(fields);
    window.localStorage.setItem(this.childPriorityStorageKey(), JSON.stringify(this.childPriorityFields));
  }

  getChildDisplayColumns(columns = this.batchColumns) {
    const fixedFields = ["material_code", "product_name"];
    const byField = new Map(columns.map((column) => [column.fieldname, column]));
    const fixed = fixedFields.map((field) => byField.get(field)).filter(Boolean);
    const selected = this.normalizeChildPriorityFields(this.childPriorityFields, columns).filter((field) => !fixedFields.includes(field));
    const prioritized = selected.map((field) => byField.get(field)).filter(Boolean);
    const used = new Set([...fixedFields, ...selected]);
    return [...fixed, ...prioritized, ...columns.filter((column) => !used.has(column.fieldname))];
  }

  openChildColumnPreferenceDialog() {
    const columns = this.batchColumns || [];
    if (!columns.length) {
      frappe.show_alert({ message: "请先展开任意一个批次，再设置 SKU 明细重点字段。", indicator: "orange" });
      return;
    }

    const fixedFields = new Set(["material_code", "product_name"]);
    const selected = new Set(this.normalizeChildPriorityFields(this.childPriorityFields, columns));
    const options = columns
      .map((column) => {
        const fixed = fixedFields.has(column.fieldname);
        const checked = fixed || selected.has(column.fieldname);
        const description = fixed ? "固定在最左侧" : "勾选后排在左侧";
        return `
          <label class="ocw-sku-priority-option ${fixed ? "is-fixed" : ""}">
            <input type="checkbox" data-sku-priority-field="${this.escape(column.fieldname)}"${checked ? " checked" : ""}${fixed ? " disabled" : ""} />
            <span>
              <strong>[${this.escape(column.excel_col)}] ${this.escape(column.label)}</strong>
              <small>${description}</small>
            </span>
          </label>
        `;
      })
      .join("");

    const dialog = new frappe.ui.Dialog({
      title: "设置 SKU 明细重点字段",
      size: "extra-large",
      fields: [
        {
          fieldtype: "HTML",
          fieldname: "sku_priority_fields",
          options: `
            <div class="ocw-sku-priority-note">勾选的字段会紧跟在“物料编码、产品名称”后面；未勾选字段不会隐藏，仍按原 Excel 顺序展示。此设置仅保存在当前浏览器。</div>
            <div class="ocw-sku-priority-grid">${options}</div>
          `,
        },
      ],
      primary_action_label: "保存",
      primary_action: () => {
        const fields = dialog.$wrapper
          .find("[data-sku-priority-field]:checked")
          .map((_, input) => $(input).attr("data-sku-priority-field"))
          .get();
        this.saveChildPriorityFields(fields);
        dialog.hide();
        this.renderTable();
        frappe.show_alert({ message: "SKU 明细字段顺序已更新", indicator: "green" });
      },
    });
    dialog.show();
    dialog.$wrapper.addClass("ocw-sku-priority-dialog");
  }

  async refreshAll() {
    await this.loadBatches();
  }

  async recalculate(batchName = "") {
    const batch = batchName ? this.findBatch(batchName) : this.getActiveBatch();
    if (!batch) return;
    this.activeBatchName = batch.name;
    this.exportPinnedBatchName = batch.name;
    try {
      const result = await this.call(
        "overseas_costing.api.calculate.recalculate_batch",
        {
          batch_name: batch.name,
          version_name: batch.current_version,
        },
        true
      );
      const summary = result.summary_snapshot || {};
      this.applyRecalculateSummary(batch.name, summary, result.allocation_rules || []);
      await this.loadBatchItems(batch.name, batch.current_version, true);
      await this.loadAuditLogs(batch.name, batch.current_version);
      this.renderTable();
      this.lastRecalculateResult = { batch_name: batch.name, summary };
      this.renderRecalculateResult(batch.name, summary);
      if (this.drawerBatchName === batch.name && this.$root.find("[data-area='batch-drawer']").hasClass("is-open")) {
        this.renderBatchDrawer();
      }
      this.recordUsage("RECALCULATE", { batch, remark: "重新试算批次成本" });
      frappe.show_alert({ message: result.message || "重新试算完成", indicator: summary.ai_allocation?.ok ? "green" : "orange" });
    } catch (error) {
      this.recordUsage("RECALCULATE", { batch, status: "Failed", remark: error.message || "重新试算失败" });
      this.showError(error);
    }
  }

  setMainView(view = "cost") {
    this.erpQueueMode = view === "erp_queue";
    if (this.erpQueueMode) {
      this.focusedBatchName = "";
      this.closeBatchDrawer({ updateUrl: false });
    }
    this.updateMainViewSwitch();
    this.renderTable();
  }

  setWorkRole(role = "purchase") {
    const nextRole = role === "finance" ? "finance" : "purchase";
    if (this.workRole === nextRole && !this.erpQueueMode) return;
    this.workRole = nextRole;
    this.erpQueueMode = false;
    this.focusedBatchName = "";
    this.closeBatchDrawer({ updateUrl: false });
    this.syncActiveSelectionWithVisible();
    this.renderTable();
    this.updateSearchResult();
  }

  setErpQueueStatus(status = "all") {
    const allowed = new Set(["all", "not_started", "pending", "success", "failed"]);
    this.erpQueueStatus = allowed.has(status) ? status : "all";
    this.renderTable();
  }

  async refreshBatch(batchName) {
    const batch = this.findBatch(batchName);
    if (!batch) return;
    this.activeBatchName = batch.name;
    this.exportPinnedBatchName = batch.name;
    try {
      await this.loadBatchItems(batch.name, batch.current_version, true);
      await this.loadAuditLogs(batch.name, batch.current_version);
      this.renderTable();
      if (this.drawerBatchName === batch.name && this.$root.find("[data-area='batch-drawer']").hasClass("is-open")) {
        if (this.erpFlowBlockState && this.erpFlowBlockState.batchName === batch.name) {
          await this.syncErpFlowBlock(batch.name);
        }
        this.renderBatchDrawer();
      }
    } catch (error) {
      this.showError(error);
    }
  }

  async confirmActualQtyFromQuantity(batchName = "") {
    const batch = this.findBatch(batchName || this.drawerBatchName || this.activeBatchName);
    if (!batch) return;
    const confirmed = await new Promise((resolve) => {
      frappe.confirm(
        `
          <div class="ocw-confirm-copy">
            <h4>按采购数量确认实际发货数量？</h4>
            <p>只会处理当前缺实际发货数量、且采购数量大于 0 的物料行；已有实际发货数量的行不会覆盖。</p>
            <div class="ocw-confirm-note">保存后会留下修改记录，并把批次标记为待重新试算。</div>
          </div>
        `,
        () => resolve(true),
        () => resolve(false)
      );
    });
    if (!confirmed) return;

    const result = await this.call(
      "overseas_costing.api.calculate.confirm_actual_shipped_qty_from_quantity",
      {
        batch_name: batch.name,
        version_name: batch.current_version || null,
        remark: "人工确认采购数量等于实际发货数量",
      },
      true
    );
    if (!result.ok) {
      throw new Error(result.message || "实际发货数量确认失败");
    }
    if (Number(result.changed_count || 0) > 0) {
      this.markBatchDirty(batch.name);
    }
    await this.loadBatchItems(batch.name, batch.current_version, true);
    await this.loadAuditLogs(batch.name, batch.current_version);
    this.expandedBatchNames.add(batch.name);
    this.renderTable();
    if (this.drawerBatchName === batch.name && this.$root.find("[data-area='batch-drawer']").hasClass("is-open")) {
      this.renderBatchDrawer();
    }
    frappe.show_alert({
      message: result.message || "实际发货数量已确认，请重新试算",
      indicator: Number(result.changed_count || 0) > 0 ? "green" : "blue",
    });
  }

  feeGapConfig(gap = {}) {
    const text = `${gap.fieldname || ""} ${gap.label || ""}`.toLowerCase();
    if (text.includes("清关") || text.includes("clearance") || text.includes("customs")) {
      return {
        feeType: "clearance",
        title: "清关费",
        uploadLabel: "上传清关资料",
        ruleCode: "manual_clearance_fee",
        expenseCategory: "清关费",
        defaultCurrency: "MXN",
        defaultBasis: "gross_weight",
        zeroRemark: "OCW_ZERO_CONFIRMED | 人工确认本票清关费为0",
      };
    }
    if (text.includes("关税") || text.includes("税费") || text.includes("tariff") || text.includes("duty") || text.includes("tax") || text.includes("igi") || text.includes("iva")) {
      return {
        feeType: "tariff",
        title: "关税/税费",
        uploadLabel: "上传完税凭证",
        ruleCode: "manual_tariff_tax",
        expenseCategory: "关税税费",
        defaultCurrency: "MXN",
        defaultBasis: "goods_value",
        zeroRemark: "OCW_ZERO_CONFIRMED | 人工确认本票关税税费为0",
      };
    }
    return null;
  }

  openFeePoolGapDialog(batchName = "", gap = {}) {
    const batch = this.findBatch(batchName || this.drawerBatchName || this.activeBatchName);
    const config = this.feeGapConfig(gap);
    if (!batch || !config) return;
    if (!batch.current_version) {
      this.showPendingFeature("当前批次还没有版本，请先生成明细并重新试算。");
      return;
    }
    const dialog = new frappe.ui.Dialog({
      title: `录入${config.title}暂估`,
      size: "large",
      fields: [
        {
          fieldtype: "HTML",
          fieldname: "fee_pool_gap",
          options: `
            <div class="ocw-purchase-preview">
              <div class="ocw-purchase-target">
                <span>当前批次</span>
                <strong>${this.escape(batch.batch_no || batch.waybill_no || batch.name)}</strong>
                <em>暂估金额会进入费用池参与综合单价试算；后续拿到正式资料后可再调整。</em>
              </div>
              <div class="ocw-manual-quote-box">
                <div class="ocw-manual-quote-head">
                  <strong>${this.escape(config.title)}暂估</strong>
                  <span>适用于暂时没有完税凭证、但已有清关/税费预计金额的情况。</span>
                </div>
                <div class="ocw-manual-quote-grid">
                  <label>
                    <span>金额</span>
                    <input class="form-control" data-field="amount" type="number" step="0.000001" placeholder="请输入大于 0 的金额">
                  </label>
                  <label>
                    <span>币种</span>
                    <select class="form-control" data-field="currency">
                      ${this.renderManualQuoteOption("MXN", "比索 MXN", config.defaultCurrency)}
                      ${this.renderManualQuoteOption("RMB", "人民币 RMB", config.defaultCurrency)}
                      ${this.renderManualQuoteOption("USD", "美元 USD", config.defaultCurrency)}
                    </select>
                  </label>
                  <label>
                    <span>分摊依据</span>
                    <select class="form-control" data-field="allocation_basis">
                      ${this.renderManualQuoteOption("goods_value", "按货值分摊", config.defaultBasis)}
                      ${this.renderManualQuoteOption("gross_weight", "按毛重分摊", config.defaultBasis)}
                      ${this.renderManualQuoteOption("chargeable_weight", "按计费重分摊", config.defaultBasis)}
                      ${this.renderManualQuoteOption("volume", "按体积分摊", config.defaultBasis)}
                    </select>
                  </label>
                  <label class="ocw-manual-quote-full">
                    <span>依据/备注</span>
                    <textarea class="form-control" data-field="remark" rows="3" placeholder="例如：按货代报价暂估，待完税凭证回来后对账调整"></textarea>
                  </label>
                </div>
                <div class="ocw-manual-quote-actions">
                  <button class="ocw-primary-btn" type="button" data-action="save-fee-pool-gap">保存暂估并重新试算</button>
                </div>
              </div>
            </div>
          `,
        },
      ],
      primary_action_label: "关闭",
      primary_action: () => dialog.hide(),
    });
    dialog.show();
    dialog.$wrapper.addClass("ocw-purchase-modal");
    dialog.$wrapper.off("click.ocwFeePoolGap").on("click.ocwFeePoolGap", "[data-action='save-fee-pool-gap']", () => {
      this.saveFeePoolGap(batch, config, dialog).catch((error) => this.showError(error));
    });
  }

  async saveFeePoolGap(batch, config, dialog) {
    const amount = this.readManualQuoteValue(dialog, "amount");
    const currency = this.readManualQuoteValue(dialog, "currency") || config.defaultCurrency;
    const allocationBasis = this.readManualQuoteValue(dialog, "allocation_basis") || config.defaultBasis;
    const remark = this.readManualQuoteValue(dialog, "remark") || `${config.title}暂估录入`;
    if (!this.isPositive(amount)) {
      frappe.msgprint(`请先填写大于 0 的${config.title}金额。`);
      return;
    }
    const confirmed = await new Promise((resolve) => {
      frappe.confirm(
        `
          <div class="ocw-confirm-copy">
            <h4>确认保存${this.escape(config.title)}暂估？</h4>
            <p>系统会把 ${this.escape(this.formatNumber(amount))} ${this.escape(currency)} 写入费用池，并立即重新试算。</p>
            <div class="ocw-confirm-note">后续拿到正式资料后，可以再次调整并保留修改记录。</div>
          </div>
        `,
        () => resolve(true),
        () => resolve(false)
      );
    });
    if (!confirmed) return;

    const $button = dialog.$wrapper.find("[data-action='save-fee-pool-gap']");
    $button.prop("disabled", true).text("保存中...");
    try {
      const result = await this.call(
        "overseas_costing.api.calculate.update_allocation_rule",
        {
          batch_name: batch.name,
          version_name: batch.current_version,
          rule_payload: JSON.stringify({
            rule_code: config.ruleCode,
            expense_category: config.expenseCategory,
            allocation_basis: allocationBasis,
            basis_field: allocationBasis,
            currency,
            amount: Number(amount),
            is_active: 1,
            is_enabled: 1,
            priority_no: config.feeType === "tariff" ? 70 : 60,
            remark: `${config.title}暂估 | ${remark}`,
          }),
        },
        true
      );
      if (!result.ok) throw new Error(result.message || `${config.title}暂估保存失败`);
      dialog.hide();
      await this.recalculate(batch.name);
    } finally {
      $button.prop("disabled", false).text("保存暂估并重新试算");
    }
  }

  async confirmZeroFeeGap(batchName = "", gap = {}) {
    const batch = this.findBatch(batchName || this.drawerBatchName || this.activeBatchName);
    const config = this.feeGapConfig(gap);
    if (!batch || !config) return;
    if (!batch.current_version) {
      this.showPendingFeature("当前批次还没有版本，请先生成明细并重新试算。");
      return;
    }
    const confirmed = await new Promise((resolve) => {
      frappe.confirm(
        `
          <div class="ocw-confirm-copy">
            <h4>确认本票${this.escape(config.title)}为 0？</h4>
            <p>系统会写入 0 元确认记录，并重新试算；之后校验结果不会再因该项缺失被阻断。</p>
            <div class="ocw-confirm-note">这不是暂估金额，表示人工确认当前票据该项无需计入综合成本。</div>
          </div>
        `,
        () => resolve(true),
        () => resolve(false)
      );
    });
    if (!confirmed) return;

    const result = await this.call(
      "overseas_costing.api.calculate.update_allocation_rule",
      {
        batch_name: batch.name,
        version_name: batch.current_version,
        rule_payload: JSON.stringify({
          rule_code: config.ruleCode,
          expense_category: config.expenseCategory,
          allocation_basis: config.defaultBasis,
          basis_field: config.defaultBasis,
          currency: config.defaultCurrency,
          amount: 0,
          is_active: 1,
          is_enabled: 1,
          priority_no: config.feeType === "tariff" ? 70 : 60,
          remark: config.zeroRemark,
        }),
      },
      true
    );
    if (!result.ok) throw new Error(result.message || `${config.title}0 元确认失败`);
    await this.recalculate(batch.name);
  }

  async confirmCalculationResult(batchName = "") {
    const batch = this.findBatch(batchName || this.drawerBatchName);
    if (!batch) return;
    try {
      const result = await this.call(
        "overseas_costing.api.writeback.confirm_calculation_result",
        {
          batch_name: batch.name,
          version_name: batch.current_version || null,
          remark: "前端人工校验计算结果",
        },
        true
      );
      if (!result.ok || result.confirmed === false) {
        this.showErpFlowBlock(result, "校验未通过");
        return;
      }
      batch.status = "Confirmed";
      batch.confirm_status = "Confirmed";
      batch.is_locked = 1;
      batch.writeback_status = batch.writeback_status || "Not Started";
      await this.refreshBatch(batch.name);
      this.recordUsage("CONFIRM_RESULT", { batch, remark: "人工校验计算结果通过" });
      frappe.show_alert({ message: result.message || "计算结果已确认", indicator: "green" });
    } catch (error) {
      this.recordUsage("CONFIRM_RESULT", { batch, status: "Failed", remark: error.message || "人工校验计算结果失败" });
      this.showError(error);
    }
  }

  async previewErpPayload(batchName = "") {
    const batch = this.findBatch(batchName || this.drawerBatchName);
    if (!batch) return;
    try {
      const result = await this.call(
        "overseas_costing.api.writeback.preview_erp_payload",
        {
          batch_name: batch.name,
          version_name: batch.current_version || null,
        },
        true
      );
      if (!result.ok || !result.ready) {
        this.showErpFlowBlock(result, "暂不能预览 ERP 报文");
        return;
      }
      this.recordUsage("PREVIEW_ERP", { batch, remark: "预览 DeepLinkERP 推送报文" });
      this.openErpPayloadPreviewDialog(result.payload || {}, result);
    } catch (error) {
      this.recordUsage("PREVIEW_ERP", { batch, status: "Failed", remark: error.message || "预览 ERP 报文失败" });
      this.showError(error);
    }
  }

  writebackToErp(batchName = "") {
    const batch = this.findBatch(batchName || this.drawerBatchName);
    if (!batch) return;
    frappe.confirm("确认将已校验的综合单价推送到 DeepLinkERP？失败后可保留日志并重试。", () => {
      this.queueErpWriteback(batch.name).catch((error) => this.showError(error));
    });
  }

  async queueErpWriteback(batchName = "") {
    const batch = this.findBatch(batchName || this.drawerBatchName);
    if (!batch) return;
    const result = await this.call(
      "overseas_costing.api.writeback.writeback_to_erp",
      {
        batch_name: batch.name,
        version_name: batch.current_version || null,
      },
      true
    );
    if (!result.ok) {
      this.recordUsage("PUSH_ERP", { batch, status: "Failed", remark: result.message || "ERP 推送未进入队列" });
      this.showErpFlowBlock(result, "ERP 推送未进入队列");
      return;
    }
    batch.writeback_status = result.writeback_status || "Pending";
    batch.writeback_message = result.message || "";
    await this.refreshBatch(batch.name);
    this.recordUsage("PUSH_ERP", { batch, remark: result.message || "推送 DeepLinkERP" });
    const indicator = String(result.writeback_status || "").toLowerCase().includes("success") ? "green" : "orange";
    frappe.show_alert({ message: result.message || "DeepLinkERP 推送已处理", indicator });
  }

  showErpFlowBlock(result = {}, title = "流程阻断") {
    const batchName = result.batch_name || this.drawerBatchName || this.activeBatchName;
    this.erpFlowBlockState = {
      batchName,
      title,
      result: {
        ...result,
        batch_name: batchName,
      },
    };
    if (this.drawerBatchName === batchName && this.$root.find("[data-area='batch-drawer']").hasClass("is-open")) {
      this.renderBatchDrawer();
    }
  }

  async syncErpFlowBlock(batchName = "") {
    const batch = this.findBatch(batchName || this.drawerBatchName || this.activeBatchName);
    if (!batch) return;
    const readiness = await this.call(
      "overseas_costing.api.writeback.check_writeback_ready",
      {
        batch_name: batch.name,
        version_name: batch.current_version || null,
      },
      false
    );
    if (readiness.ok && readiness.ready) {
      if (this.erpFlowBlockState && this.erpFlowBlockState.batchName === batch.name) {
        this.erpFlowBlockState = null;
      }
      return readiness;
    }
    this.erpFlowBlockState = {
      batchName: batch.name,
      title: "校验未通过",
      result: readiness || {},
    };
    return readiness;
  }

  renderErpFlowBlockInline(batch) {
    if (!this.erpFlowBlockState || this.erpFlowBlockState.batchName !== batch.name) return "";
    const state = this.erpFlowBlockState;
    return `
      <div class="ocw-erp-block-inline">
        ${this.renderErpFlowBlockContent(state.result || {}, state.title || "流程阻断")}
      </div>
    `;
  }

  renderErpFlowBlockContent(result = {}, title = "流程阻断") {
    const reasons = Array.isArray(result.blocking_reasons) ? result.blocking_reasons : [];
    const fieldGaps = result.field_gaps || {};
    const gapHtml = this.renderErpFieldGapsWithActions(
      fieldGaps,
      result.batch_name || this.drawerBatchName || this.activeBatchName,
      result
    );
    const reasonHtml = reasons.length
      ? `<ul>${reasons.map((reason) => `<li>${this.escape(reason)}</li>`).join("")}</ul>`
      : `<p>${this.escape(result.message || "请补齐基础数据或重新试算后再继续。")}</p>`;
    return `
      <div class="ocw-erp-block-dialog">
        <div class="ocw-erp-block-head">
          <div>
            <h5>${this.escape(title)}</h5>
            <span>${this.escape(reasons.length ? `待补信息共 ${reasons.length} 项` : result.message || "请补齐基础数据或重新试算后再继续。")}</span>
          </div>
        </div>
        ${gapHtml}
        <div class="ocw-erp-block-reason">${reasonHtml}</div>
      </div>
    `;
  }
  renderErpFieldGaps(fieldGaps = {}) {
    const sections = [
      { key: "batch", title: "批次头待补" },
      { key: "rules", title: "费用池待补" },
      { key: "items", title: "明细待补" },
    ];
    const summary = fieldGaps.summary || {};
    const html = sections
      .map((section) => {
        const rows = Array.isArray(fieldGaps[section.key]) ? fieldGaps[section.key] : [];
        if (!rows.length) return "";
        const list = rows
          .map(
            (row) => `
              <li>
                <strong>${this.escape(row.label || row.fieldname || "--")}</strong>
                <span>${this.escape(row.suggestion || row.source_hint || "")}</span>
              </li>
            `
          )
          .join("");
        return `
          <div class="ocw-erp-gap-group">
            <h5>${this.escape(section.title)}（${this.escape(String(rows.length))} 项）</h5>
            <ul>${list}</ul>
          </div>
        `;
      })
      .filter(Boolean)
      .join("");
    if (!html) return "";
    const total = summary.missing_total ?? sections.reduce((count, section) => count + ((Array.isArray(fieldGaps[section.key]) ? fieldGaps[section.key].length : 0)), 0);
    return `
      <div class="ocw-erp-gap-summary">
        <div class="ocw-erp-gap-total">待补信息共 ${this.escape(String(total))} 项</div>
        ${html}
      </div>
    `;
  }

  renderErpFieldGapsWithActions(fieldGaps = {}, batchName = "", readiness = {}) {
    const sections = [
      { key: "batch", title: "批次头待补" },
      { key: "rules", title: "费用池待补" },
      { key: "items", title: "明细待补" },
    ];
    const batch = batchName ? this.findBatch(batchName) : this.findBatch(this.drawerBatchName || this.activeBatchName);
    const summary = fieldGaps.summary || {};
    const html = sections
      .map((section) => {
        const rows = Array.isArray(fieldGaps[section.key]) ? fieldGaps[section.key] : [];
        if (!rows.length) return "";
        const list = rows.map((row) => this.renderErpGapRow(section.key, row, batch, readiness)).join("");
        return `
          <div class="ocw-erp-gap-group">
            <h5>${this.escape(section.title)}（${this.escape(String(rows.length))}项）</h5>
            <ul>${list}</ul>
          </div>
        `;
      })
      .filter(Boolean)
      .join("");
    if (!html) return "";
    const total = summary.missing_total ?? sections.reduce((count, section) => count + ((Array.isArray(fieldGaps[section.key]) ? fieldGaps[section.key].length : 0)), 0);
    return `
      <div class="ocw-erp-gap-summary">
        <div class="ocw-erp-gap-total">待补信息共 ${this.escape(String(total))} 项</div>
        ${html}
      </div>
    `;
  }

  renderErpGapRow(scope, row = {}, batch = null, readiness = {}) {
    const rowLabel = row.label || row.fieldname || "--";
    const detailLabel = [row.row_no || row.excel_row_no || "", row.material_code || "", row.product_name || ""].filter(Boolean).join(" / ");
    const examples = Array.isArray(readiness.item_issue_examples) ? readiness.item_issue_examples : [];
    const matchedExample = scope === "items"
      ? examples.find((example) => (example.missing_fieldnames || []).includes(row.fieldname))
      : null;
    const buttons = [];
    if (batch && (scope === "batch" || scope === "rules")) {
      buttons.push(`<button class="ocw-link-btn" type="button" data-action="gap-repull-dingtalk" data-batch-name="${this.escape(batch.name)}">重拉钉钉</button>`);
    }
    if (batch && scope === "rules") {
      const feeConfig = this.feeGapConfig(row);
      if (feeConfig) {
        buttons.push(`<button class="ocw-link-btn" type="button" data-action="gap-open-source-center" data-batch-name="${this.escape(batch.name)}" data-gap-fieldname="${this.escape(row.fieldname || "")}" data-gap-label="${this.escape(row.label || "")}">${this.escape(feeConfig.uploadLabel)}</button>`);
        buttons.push(`<button class="ocw-link-btn" type="button" data-action="gap-open-fee-pool" data-batch-name="${this.escape(batch.name)}" data-gap-fieldname="${this.escape(row.fieldname || "")}" data-gap-label="${this.escape(row.label || "")}">录入暂估</button>`);
        buttons.push(`<button class="ocw-link-btn" type="button" data-action="gap-confirm-zero-fee" data-batch-name="${this.escape(batch.name)}" data-gap-fieldname="${this.escape(row.fieldname || "")}" data-gap-label="${this.escape(row.label || "")}">确认为0</button>`);
      } else {
        buttons.push(`<button class="ocw-link-btn" type="button" data-action="gap-open-source-center" data-batch-name="${this.escape(batch.name)}" data-gap-fieldname="${this.escape(row.fieldname || "")}" data-gap-label="${this.escape(row.label || "")}">去补资料</button>`);
      }
    }
    if (batch && scope === "items") {
      if (row.fieldname === "actual_shipped_qty") {
        buttons.push(`<button class="ocw-link-btn" type="button" data-action="gap-open-source-center" data-batch-name="${this.escape(batch.name)}" data-gap-fieldname="${this.escape(row.fieldname || "")}" data-gap-label="${this.escape(row.label || "")}">上传装箱单</button>`);
        buttons.push(`<button class="ocw-link-btn" type="button" data-action="gap-confirm-actual-qty" data-batch-name="${this.escape(batch.name)}">按采购数量确认</button>`);
      }
      buttons.push(`<button class="ocw-link-btn" type="button" data-action="gap-open-item-edit" data-batch-name="${this.escape(batch.name)}" data-item-name="${this.escape((matchedExample && matchedExample.item_name) || row.item_name || "")}" data-fieldname="${this.escape(row.fieldname || "")}">去补录</button>`);
    }
    if (batch) {
      buttons.push(`<button class="ocw-link-btn" type="button" data-action="gap-recalculate" data-batch-name="${this.escape(batch.name)}">重新试算</button>`);
    }
    return `
      <li class="ocw-erp-gap-row">
        <div class="ocw-erp-gap-main">
          <strong>${this.escape(rowLabel)}</strong>
          <span>${this.escape(row.suggestion || row.source_hint || "")}</span>
          ${detailLabel ? `<em>${this.escape(detailLabel)}</em>` : ""}
        </div>
        <div class="ocw-erp-gap-actions">${buttons.join("")}</div>
      </li>
    `;
  }

  openErpPayloadPreviewDialog(payload = {}, result = {}) {
    const items = Array.isArray(payload.items) ? payload.items : [];
    const pools = payload.expense_pools || {};
    const allocations = pools.item_allocations || {};
    const rows = items.slice(0, 12).map((item, index) => {
      const formula = item.cost_formula || {};
      return `
        <tr>
          <td>${this.escape(String(index + 1))}</td>
          <td>${this.escape(this.formatValue(item.material_code || "--"))}</td>
          <td>${this.escape(this.formatValue(item.original_unit_price ?? formula.original_unit_price ?? "--"))}</td>
          <td>${this.escape(this.formatValue(item.comprehensive_unit_price ?? formula.comprehensive_unit_price ?? "--"))}</td>
          <td>${this.escape(this.formatValue(item.outbound_quantity ?? "--"))}</td>
          <td>${this.escape(this.formatValue(formula.allocated_logistics_cost ?? 0))}</td>
          <td>${this.escape(this.formatValue(formula.allocated_clearance_tax_cost ?? 0))}</td>
        </tr>
      `;
    }).join("");
    const jsonText = JSON.stringify(payload, null, 2);
    const dialog = new frappe.ui.Dialog({
      title: "DeepLinkERP 报文预览",
      size: "extra-large",
      fields: [
        {
          fieldtype: "HTML",
          fieldname: "erp_payload_preview",
          options: `
            <div class="ocw-erp-preview">
              <div class="ocw-erp-preview-summary">
                <div><span>目标系统</span><strong>${this.escape(payload.target_system || "DeepLinkERP")}</strong></div>
                <div><span>业务主体</span><strong>${this.escape(payload.subsidiary_code || "--")}</strong></div>
                <div><span>批次</span><strong>${this.escape(payload.batch_no || payload.batch_name || result.batch_name || "--")}</strong></div>
                <div><span>版本</span><strong>${this.escape(payload.version_name || result.version_name || "--")}</strong></div>
                <div><span>物料行数</span><strong>${this.escape(this.formatValue(payload.item_count || items.length || 0))}</strong></div>
                <div><span>综合成本</span><strong>${this.escape(this.formatNumber(payload.total_cost_rmb || 0))} RMB</strong></div>
              </div>
              <div class="ocw-erp-pool-strip">
                <span>物流 ${this.escape(this.formatNumber(allocations.logistics_allocated_rmb || 0))} RMB</span>
                <span>清关 ${this.escape(this.formatNumber(allocations.clearance_fee_rmb || 0))} RMB</span>
                <span>关税 ${this.escape(this.formatNumber(allocations.tariff_tax_total || 0))}</span>
                <span>规则 ${this.escape(this.formatValue((pools.rules || []).length || 0))} 条</span>
              </div>
              <div class="ocw-erp-preview-table-wrap">
                <table class="ocw-erp-preview-table">
                  <thead><tr><th>#</th><th>物料编码</th><th>原始单价</th><th>综合单价</th><th>出库数量</th><th>分摊物流</th><th>清关/关税</th></tr></thead>
                  <tbody>${rows || `<tr><td colspan="7">暂无物料明细</td></tr>`}</tbody>
                </table>
              </div>
              <details class="ocw-erp-json-detail">
                <summary>查看技术报文 JSON</summary>
                <pre class="ocw-erp-json-preview">${this.escape(jsonText)}</pre>
              </details>
            </div>
          `,
        },
      ],
      primary_action_label: "关闭",
      primary_action: () => dialog.hide(),
    });
    dialog.show();
    dialog.$wrapper.addClass("ocw-erp-preview-modal");
  }

  applyRecalculateSummary(batchName, summary, allocationRules = []) {
    const batch = this.findBatch(batchName);
    if (!batch) return;
    batch.status = "Calculated";
    if (summary.item_count !== undefined) batch.item_count = summary.item_count;
    if (summary.total_goods_value !== undefined) batch.total_goods_value = summary.total_goods_value;
    if (summary.total_gross_weight_kg !== undefined) batch.total_gross_weight_kg = summary.total_gross_weight_kg;
    if (summary.total_cost_rmb !== undefined) batch.estimated_total_cost_rmb = summary.total_cost_rmb;
    batch.summary_snapshot = summary;
    batch.ai_allocation = summary.ai_allocation || {};
    if (Array.isArray(allocationRules)) batch.allocation_rule_snapshot = allocationRules;

  }

  openFileParseDialog() {
    const selectableBatches = this.getSelectableBatches();
    const batch = this.getSelectableBatch("", selectableBatches);
    const batchName = batch ? batch.name : "";
    const batchHint = this.voucherBatchHint(batch);
    const batchOptions = this.renderSelectableBatchOptions(batchName, selectableBatches);
    const batchSelectDisabled = selectableBatches.length ? "" : " disabled";
    const dialog = new frappe.ui.Dialog({
      title: "完税凭证对比",
      fields: [
        {
          fieldtype: "HTML",
          fieldname: "file_parse",
          options: `
            <div class="ocw-file-parse-box">
              <div class="ocw-voucher-target">
                <label class="ocw-voucher-batch-picker">
                  <span>对比批次</span>
                  <select class="form-control ocw-batch-select" data-role="voucher-batch-select" aria-label="选择凭证对比批次"${batchSelectDisabled}>${batchOptions}</select>
                </label>
                <em data-area="voucher-batch-hint">${this.escape(batchHint)}</em>
              </div>
              <label class="ocw-import-file-label">上传完税凭证 PDF</label>
              <div class="ocw-import-dropzone" data-voucher-dropzone="1" tabindex="0">
                <input class="ocw-voucher-file-input" type="file" accept=".pdf" />
                <div class="ocw-import-drop-icon">PDF</div>
                <div>
                  <strong data-area="voucher-file-name">拖放 PDF 到这里，或点击选择</strong>
                  <span>当前仅做完税凭证识别与系统数据对比，不写入成本表。</span>
                </div>
              </div>
              <div class="ocw-import-preview-actions">
                <button class="ocw-outline-btn ocw-mini-btn" type="button" data-action="preview-voucher">对比预览</button>
                <span data-area="voucher-preview-status">选择文件后可先对比凭证字段。</span>
              </div>
              <div class="ocw-voucher-preview empty" data-area="voucher-preview">尚未对比</div>
              <div class="ocw-voucher-records">
                <div class="ocw-voucher-records-head">
                  <strong>已保存对比记录</strong>
                  <div class="ocw-voucher-records-actions">
                    <button class="ocw-outline-btn ocw-mini-btn" type="button" data-action="refresh-voucher-records">刷新</button>
                    <button class="ocw-danger-btn ocw-mini-btn" type="button" data-action="delete-voucher-records">删除</button>
                  </div>
                </div>
                <div class="ocw-voucher-record-list loading" data-area="voucher-records">加载中</div>
              </div>
            </div>
          `,
        },
      ],
      primary_action_label: "保存对比结果",
      primary_action: async () => {
        try {
          await this.saveTaxCertificateParseResult(dialog);
        } catch (error) {
          this.showError(error);
        }
      },
    });
    dialog.show();
    dialog.$wrapper.addClass("ocw-voucher-modal");
    this.activeVoucherParseDialog = dialog;
    dialog.$wrapper.data("ocw-voucher-batch-name", batchName);
    this.updateVoucherPrimarySaveAction(dialog, false);
    this.bindVoucherDropzone(dialog);
    this.loadTaxCertificateRecords(dialog).catch((error) => this.showError(error));
  }

  bindVoucherDropzone(dialog) {
    const $dropzone = dialog.$wrapper.find("[data-voucher-dropzone='1']");
    const $input = dialog.$wrapper.find(".ocw-voucher-file-input");
    const $fileName = dialog.$wrapper.find("[data-area='voucher-file-name']");
    const setFile = (file) => {
      if (!file) return;
      dialog.$wrapper.data("ocw-voucher-file", file);
      dialog.$wrapper.removeData("ocw-voucher-upload");
      $fileName.text(file.name);
      $dropzone.addClass("has-file");
      this.renderVoucherPreview(dialog, null, "empty");
    };

    $dropzone.on("click keydown", (event) => {
      if (event.type === "keydown" && !["Enter", " "].includes(event.key)) return;
      event.preventDefault();
      $input.trigger("click");
    });
    $input.on("click", (event) => event.stopPropagation());
    $input.on("change", (event) => setFile(event.currentTarget.files?.[0]));
    $dropzone.on("dragenter dragover", (event) => {
      event.preventDefault();
      event.stopPropagation();
      $dropzone.addClass("is-dragover");
    });
    $dropzone.on("dragleave dragend drop", (event) => {
      event.preventDefault();
      event.stopPropagation();
      $dropzone.removeClass("is-dragover");
    });
    $dropzone.on("drop", (event) => {
      setFile(event.originalEvent?.dataTransfer?.files?.[0]);
    });
    dialog.$wrapper.on("change", "[data-role='voucher-batch-select']", (event) => {
      const batch = this.findSelectableBatch(String($(event.currentTarget).val() || ""));
      dialog.$wrapper.data("ocw-voucher-batch-name", batch ? batch.name : "");
      dialog.$wrapper.removeData("ocw-voucher-preview");
      this.renderVoucherPreview(dialog, null, "empty");
      this.updateVoucherPrimarySaveAction(dialog, false);
      dialog.$wrapper.find("[data-area='voucher-batch-hint']").text(this.voucherBatchHint(batch));
      this.loadTaxCertificateRecords(dialog).catch((error) => this.showError(error));
    });
    dialog.$wrapper.on("click", "[data-action='preview-voucher']", (event) => {
      event.preventDefault();
      this.previewTaxCertificate(dialog).catch((error) => this.showError(error));
    });
    dialog.$wrapper.on("click", "[data-action='save-voucher-parse']", (event) => {
      event.preventDefault();
      this.saveTaxCertificateParseResult(dialog).catch((error) => this.showError(error));
    });
    dialog.$wrapper.on("click", "[data-action='refresh-voucher-records']", (event) => {
      event.preventDefault();
      this.loadTaxCertificateRecords(dialog).catch((error) => this.showError(error));
    });
    dialog.$wrapper.on("click", "[data-action='delete-voucher-records']", (event) => {
      event.preventDefault();
      this.deleteTaxCertificateRecords(dialog).catch((error) => this.showError(error));
    });
    dialog.$wrapper.on("click", "[data-action='open-voucher-record']", (event) => {
      event.preventDefault();
      const recordName = $(event.currentTarget).attr("data-record-name");
      if (recordName) this.openTaxCertificateRecordDialog(recordName).catch((error) => this.showError(error));
    });
  }

  getVoucherDialogFile(dialog) {
    return dialog.$wrapper.data("ocw-voucher-file") || dialog.$wrapper.find(".ocw-voucher-file-input").get(0)?.files?.[0] || null;
  }

  validateVoucherFile(file) {
    if (!file) {
      frappe.msgprint("请先上传完税凭证 PDF。");
      return false;
    }
    if (!this.isPdfFileRef(file.name || "")) {
      frappe.msgprint("请上传 .pdf 格式的完税凭证。");
      return false;
    }
    return true;
  }

  async ensureVoucherFileUploaded(dialog, file) {
    const uploaded = dialog.$wrapper.data("ocw-voucher-upload");
    const sameFile =
      uploaded &&
      uploaded.file_url &&
      uploaded.source_file_name === file.name &&
      uploaded.source_file_size === file.size &&
      uploaded.source_file_modified === file.lastModified;
    if (sameFile) return uploaded;

    const uploadResult = await this.uploadImportFile(file);
    const normalized = {
      ...uploadResult,
      source_file_name: file.name,
      source_file_size: file.size,
      source_file_modified: file.lastModified,
    };
    dialog.$wrapper.data("ocw-voucher-upload", normalized);
    return normalized;
  }

  async previewTaxCertificate(dialog) {
    const file = this.getVoucherDialogFile(dialog);
    if (!this.validateVoucherFile(file)) return;

    this.renderVoucherPreview(dialog, null, "loading");
    const uploaded = await this.ensureVoucherFileUploaded(dialog, file);
    const result = await this.call(
      "overseas_costing.api.import_api.preview_tax_certificate_pdf",
      {
        source_name: uploaded.file_name || file.name,
        file_url: uploaded.file_url,
        batch_name: dialog.$wrapper.data("ocw-voucher-batch-name") || "",
      },
      true
    );
    dialog.$wrapper.data("ocw-voucher-preview", result);
    this.renderVoucherPreview(dialog, result, "ready");
  }

  async saveTaxCertificateParseResult(dialog) {
    const file = this.getVoucherDialogFile(dialog);
    if (!this.validateVoucherFile(file)) return;

    const preview = dialog.$wrapper.data("ocw-voucher-preview") || {};
    if (!preview.ok) {
      frappe.msgprint("请先点击「对比预览」，确认凭证已匹配到系统批次后再保存。");
      return;
    }
    const canSave = Boolean(preview.reconciliation && preview.reconciliation.batch && preview.reconciliation.batch.name);
    if (!canSave) {
      frappe.msgprint("当前凭证还没有匹配到系统批次，暂不能保存对比结果。");
      return;
    }

    this.updateVoucherPrimarySaveAction(dialog, false, "保存中");
    let result;
    try {
      const uploaded = await this.ensureVoucherFileUploaded(dialog, file);
      result = await this.call(
        "overseas_costing.api.import_api.save_tax_certificate_parse_result",
        {
          source_name: uploaded.file_name || file.name,
          file_url: uploaded.file_url,
          batch_name: dialog.$wrapper.data("ocw-voucher-batch-name") || "",
        },
        true
      );
    } catch (error) {
      this.updateVoucherPrimarySaveAction(dialog, canSave);
      throw error;
    }
    if (!result || !result.ok) {
      frappe.msgprint((result && result.message) || "保存对比结果失败。");
      this.updateVoucherPrimarySaveAction(dialog, canSave);
      return;
    }
    frappe.show_alert({
      message: result.message || "保存完成。",
      indicator: result.fx_sync && result.fx_sync.action === "updated" ? "orange" : "green",
    });
    if (result.batch_name) {
      await this.refreshBatch(result.batch_name).catch((error) => this.showError(error));
    }
    try {
      await this.loadTaxCertificateRecords(dialog);
    } catch (error) {
      this.showError(error);
    }
    this.resetVoucherDialogAfterSave(dialog);
  }

  async loadTaxCertificateRecords(dialog) {
    const $records = dialog.$wrapper.find("[data-area='voucher-records']");
    $records.removeClass("empty ready").addClass("loading").text("加载中");
    const result = await this.call(
      "overseas_costing.api.import_api.list_tax_certificate_parse_records",
      {
        batch_name: dialog.$wrapper.data("ocw-voucher-batch-name") || "",
        limit: 10,
      },
      false
    );
    this.renderTaxCertificateRecords(dialog, result);
  }

  renderTaxCertificateRecords(dialog, result) {
    const $records = dialog.$wrapper.find("[data-area='voucher-records']");
    const items = (result && result.items) || [];
    const recordNames = items.map((row) => String((row && row.name) || "").trim()).filter(Boolean);
    dialog.$wrapper.data("ocw-voucher-record-names", recordNames);
    dialog.$wrapper.data("ocw-voucher-record-count", recordNames.length);
    dialog.$wrapper.find("[data-action='delete-voucher-records']").prop("disabled", false);
    $records.removeClass("loading ready empty");
    if (!items.length) {
      $records.addClass("empty").text("暂无保存记录");
      return;
    }
    const fallbackTip = result.fallback_recent ? `<div class="ocw-voucher-record-tip">当前批次暂无凭证记录，以下为最近保存记录。</div>` : "";
    $records.addClass("ready").html(`
      ${fallbackTip}
      ${items.map((row) => this.renderTaxCertificateRecord(row)).join("")}
    `);
  }

  renderTaxCertificateRecord(row) {
    const batch = row.batch || {};
    const resolution = row.manual_resolution || {};
    const statusClass = this.voucherValidationPreviewClass(row.reconciliation_status || row.validation_status || "review");
    const batchLabel = batch.customs_no || batch.waybill_no || batch.batch_no || batch.name || "--";
    const itemCount = `${row.item_count || 0} / ${row.declared_item_count ?? "--"}`;
    const resolutionLabel = resolution.status_label || row.manual_resolution_status_label || "未处理";
    return `
      <div class="ocw-voucher-record ${this.escape(statusClass)}">
        <div class="ocw-voucher-record-main">
          <strong>${this.escape(row.source_doc_no || row.customs_no || "--")}</strong>
          <span>${this.escape(batchLabel)} · ${this.escape(row.file_name || "--")}</span>
        </div>
        <div class="ocw-voucher-record-grid">
          <div><span>状态</span><b>${this.escape(row.reconciliation_status_label || row.validation_status_label || row.parse_status || "--")}</b></div>
          <div><span>凭证税费 MXN</span><b>${this.escape(this.formatValidationValue(row.paid_total_mxn))}</b></div>
          <div><span>系统税费 MXN</span><b>${this.escape(this.formatValidationValue(row.system_tax_total_mxn))}</b></div>
          <div><span>差额 MXN</span><b>${this.escape(this.formatValidationValue(row.tax_total_diff_mxn))}</b></div>
          <div><span>差额方向</span><b>${this.escape(row.direction_label || "--")}</b></div>
          <div><span>人工处理</span><b>${this.escape(resolutionLabel)}</b></div>
          <div><span>行数</span><b>${this.escape(itemCount)}</b></div>
          <div><span>保存时间</span><b>${this.escape(this.formatValue(row.modified || row.creation || "--"))}</b></div>
          <div class="ocw-voucher-record-action">
            <button class="ocw-outline-btn ocw-mini-btn" type="button" data-action="open-voucher-record" data-record-name="${this.escape(row.name)}">查看记录</button>
          </div>
        </div>
      </div>
    `;
  }

  async deleteTaxCertificateRecords(dialog) {
    const batchName = dialog.$wrapper.data("ocw-voucher-batch-name") || "";
    const recordNames = dialog.$wrapper.data("ocw-voucher-record-names") || [];
    const targetNames = Array.isArray(recordNames) ? recordNames.filter(Boolean) : [];
    const recordCount = targetNames.length;
    if (!recordCount) {
      frappe.msgprint("当前列表没有可删除的对比记录。");
      return;
    }
    frappe.confirm(
      `确认删除当前列表显示的 ${recordCount} 条完税凭证对比记录？删除后只移除对比记录，不会删除批次和物料明细。`,
      async () => {
        const result = await this.call(
          "overseas_costing.api.import_api.delete_tax_certificate_parse_records",
          { record_names_json: JSON.stringify(targetNames) },
          true
        );
        if (!result || !result.ok) {
          frappe.msgprint((result && result.message) || "删除对比记录失败。");
          return;
        }
        frappe.show_alert({ message: result.message || "对比记录已删除。", indicator: "green" });
        await this.loadTaxCertificateRecords(dialog);
        await this.refreshBatch(batchName).catch((error) => this.showError(error));
      }
    );
  }

  async openTaxCertificateRecordDialog(recordName) {
    const result = await this.call(
      "overseas_costing.api.import_api.get_tax_certificate_parse_record",
      { record_name: recordName },
      true
    );
    if (!result || !result.ok) {
      frappe.msgprint((result && result.message) || "未能读取完税凭证对比记录。");
      return;
    }

    const detailDialog = new frappe.ui.Dialog({
      title: "完税凭证对比记录",
      fields: [
        {
          fieldtype: "HTML",
          fieldname: "voucher_record_detail",
          options: this.renderTaxCertificateRecordDetail(result),
        },
      ],
      primary_action_label: "关闭",
      primary_action: () => detailDialog.hide(),
    });
    detailDialog.show();
    detailDialog.$wrapper.addClass("ocw-voucher-modal ocw-voucher-record-modal");
    detailDialog.$wrapper.on("click", "[data-action='resolve-voucher-record']", (event) => {
      event.preventDefault();
      this.submitVoucherManualResolution(detailDialog, recordName).catch((error) => this.showError(error));
    });
    detailDialog.$wrapper.on("change", "[data-field='resolution_confirm']", (event) => {
      const checked = $(event.currentTarget).is(":checked");
      detailDialog.$wrapper.find("[data-action='resolve-voucher-record']").prop("disabled", !checked);
    });
  }

  renderTaxCertificateRecordDetail(result) {
    const record = result.record_summary || {};
    const parseResult = result.parse_result || {};
    const mappedResult = result.mapped_result || {};
    const header = parseResult.header || {};
    const summary = parseResult.summary || {};
    const taxes = parseResult.tax_totals || {};
    const items = parseResult.line_items || [];
    const validation = parseResult.validation || {};
    const validationStatus = validation.status || record.validation_status || "review";
    const validationText = validation.status_label || record.validation_status_label || "--";
    const batch = record.batch || mappedResult.batch || {};
    const batchLabel = batch.customs_no || batch.waybill_no || batch.batch_no || batch.container_no || batch.name || "--";
    const itemCount = `${summary.item_count || items.length || record.item_count || 0} / ${summary.declared_item_count ?? record.declared_item_count ?? "--"}`;
    const rows = items.map((row) => this.renderVoucherItemRow(row)).join("");
    const fxSync = parseResult.fx_sync || {};
    const rawPaymentDate = header.payment_date || record.payment_date || "";
    const paymentDateText = this.formatVoucherPaymentDate(rawPaymentDate, fxSync.normalized_payment_date || fxSync.payment_date || "");
    const systemFxInfo = this.formatSystemPaymentFx(fxSync, rawPaymentDate);

    return `
      <div class="ocw-voucher-record-detail">
        <div class="ocw-voucher-validation-head ${this.escape(validationStatus)}">
          <div>
            <span>解析校验</span>
            <strong>${this.escape(validationText)}</strong>
          </div>
          <p>这是已保存的解析快照，只用于复看和复核，不会重新解析文件或写入成本字段。</p>
        </div>
        <div class="ocw-voucher-summary">
          <div><span>报关单号</span><strong>${this.escape(record.customs_no || header.pedimento_no || "--")}</strong></div>
          <div><span>凭证参考号</span><strong>${this.escape(header.pedimento_ref || header.pedimento_short_no || record.pedimento_ref || "--")}</strong></div>
          <div><span>柜号</span><strong>${this.escape(record.container_no || header.container_no || "--")}</strong></div>
          <div><span>匹配批次</span><strong>${this.escape(batchLabel)}</strong></div>
          <div><span>文件名</span><strong title="${this.escape(record.file_name || parseResult.source_name || "")}">${this.escape(record.file_name || parseResult.source_name || "--")}</strong></div>
          <div><span>支付日期</span><strong title="${this.escape(rawPaymentDate)}">${this.escape(paymentDateText)}</strong></div>
          <div><span>凭证原始汇率</span><strong>${this.escape(this.formatValidationValue(header.exchange_rate))}</strong></div>
          <div class="ocw-voucher-summary-wide">
            <span>${this.escape(systemFxInfo.heading || "系统采用汇率")}</span>
            <div class="ocw-system-fx-lines" title="${this.escape(systemFxInfo.title)}">
              ${systemFxInfo.lines.map((line) => `<strong>${this.escape(line)}</strong>`).join("")}
            </div>
          </div>
          <div><span>毛重 KG</span><strong>${this.escape(this.formatValidationValue(header.gross_weight_kg))}</strong></div>
          <div><span>支付总额 MXN</span><strong>${this.escape(this.formatValidationValue(summary.paid_total_mxn ?? record.paid_total_mxn))}</strong></div>
          <div><span>税费合计 MXN</span><strong>${this.escape(this.formatValidationValue(summary.tax_total_sum_mxn ?? record.tax_total_sum_mxn))}</strong></div>
          <div><span>保存时间</span><strong>${this.escape(this.formatValue(record.modified || record.creation || "--"))}</strong></div>
          <div><span>商品分项</span><strong>${this.escape(itemCount)}</strong></div>
        </div>
        <div class="ocw-voucher-tax-chips">${this.renderVoucherTaxChips(taxes)}</div>
        ${this.renderVoucherReconciliation(mappedResult, { showSaveButton: false })}
        ${this.renderVoucherManualResolution(record, mappedResult)}
        ${this.renderVoucherValidation(validation)}
        <div class="ocw-voucher-table-wrap">
          <table class="ocw-voucher-table">
            <thead>
              <tr>
                <th>序号</th>
                <th>HS 编码</th>
                <th>海关进口名称</th>
                <th>数量</th>
                <th>IGI 税率</th>
                <th>IGI 税额</th>
                <th>IVA 税率</th>
                <th>IVA 税额</th>
              </tr>
            </thead>
            <tbody>${rows || `<tr><td colspan="8">未识别到商品分项</td></tr>`}</tbody>
          </table>
        </div>
        <div class="ocw-voucher-more">共 ${this.escape(String(items.length || 0))} 条分项。</div>
      </div>
    `;
  }

  renderVoucherManualResolution(record, mappedResult = {}) {
    const resolution = mappedResult.manual_resolution || record.manual_resolution || {};
    const voucher = mappedResult.voucher || {};
    const system = mappedResult.system || {};
    const diff = mappedResult.difference || {};
    const hasResolution = Boolean(resolution.action);
    const selected = resolution.action || "accept_difference";
    const adjustedValue = resolution.final_source === "manual_adjust" ? resolution.final_tax_total_mxn : "";
    const rawHistory = Array.isArray(mappedResult.manual_resolution_history) ? mappedResult.manual_resolution_history : [];
    const history = rawHistory.slice();
    if (hasResolution) {
      const currentKey = `${resolution.resolved_at || ""}|${resolution.action || ""}|${resolution.final_tax_total_mxn ?? ""}`;
      const hasCurrent = history.some((item) => {
        const row = item || {};
        return `${row.resolved_at || ""}|${row.action || ""}|${row.final_tax_total_mxn ?? ""}` === currentKey;
      });
      if (!hasCurrent) {
        history.push(resolution);
      }
    }
    const options = [
      ["accept_difference", "确认差异可接受"],
      ["mark_exception", "备注异常"],
      ["use_voucher", "按凭证金额为准"],
      ["keep_system", "保留系统金额"],
      ["manual_adjust", "手工调整金额"],
    ]
      .map(([value, label]) => `<option value="${this.escape(value)}" ${selected === value ? "selected" : ""}>${this.escape(label)}</option>`)
      .join("");
    const savedHtml = hasResolution
      ? `
        <div class="ocw-voucher-resolution-saved">
          <div><span>当前处理</span><strong>${this.escape(resolution.status_label || resolution.action_label || "--")}</strong></div>
          <div><span>采用金额 MXN</span><strong>${this.escape(this.formatValidationValue(resolution.final_tax_total_mxn))}</strong></div>
          <div><span>采用依据</span><strong>${this.escape(resolution.final_source_label || "--")}</strong></div>
          <div><span>处理人</span><strong>${this.escape(resolution.resolved_by || "--")}</strong></div>
          <div><span>处理时间</span><strong>${this.escape(resolution.resolved_at || "--")}</strong></div>
          <p>${this.escape(resolution.message || resolution.remark || "")}</p>
        </div>
      `
      : `<div class="ocw-voucher-resolution-empty">当前差异尚未人工处理。</div>`;
    const historyRows = history
      .slice()
      .reverse()
      .slice(0, 8)
      .map((item) => {
        const row = item || {};
        return `
          <div>
            <strong>${this.escape(row.action_label || row.status_label || "--")}</strong>
            <em>${this.escape(row.resolved_at || "--")} / ${this.escape(row.resolved_by || "--")}</em>
            <small>${this.escape(row.message || row.remark || "未填写备注")}</small>
          </div>
        `;
      })
      .join("");
    const historyHtml = `
      <div class="ocw-voucher-resolution-history">
        <span>处理记录</span>
        ${historyRows || `<p>暂无处理记录，提交后会显示在这里。</p>`}
      </div>
    `;
    return `
      <div class="ocw-voucher-resolution">
        <div class="ocw-voucher-resolution-head">
          <div>
            <span>人工处理差异</span>
            <strong>${this.escape(hasResolution ? "已处理，可重新调整" : "待处理")}</strong>
          </div>
          <p>可选择凭证金额、系统金额或手工调整金额为准；这里只保存处理记录，不会自动改成本字段。</p>
        </div>
        <div class="ocw-voucher-resolution-grid">
          <div><span>凭证税费 MXN</span><strong>${this.escape(this.formatValidationValue(voucher.paid_total_mxn))}</strong></div>
          <div><span>系统税费 MXN</span><strong>${this.escape(this.formatValidationValue(system.system_import_tax_total_mxn))}</strong></div>
          <div><span>原差额 MXN</span><strong>${this.escape(this.formatValidationValue(diff.tax_total_diff_mxn))}</strong></div>
          <div><span>方向</span><strong>${this.escape(diff.direction_label || "--")}</strong></div>
        </div>
        <div class="ocw-voucher-resolution-form">
          <label>
            <span>处理方式</span>
            <select data-field="resolution_action">${options}</select>
          </label>
          <label>
            <span>调整后税费 MXN</span>
            <input type="number" step="0.01" data-field="adjusted_tax_total_mxn" value="${this.escape(adjustedValue ?? "")}" placeholder="选择手工调整时填写" />
          </label>
          <label class="ocw-voucher-resolution-remark">
            <span>处理备注</span>
            <input type="text" data-field="resolution_remark" value="${this.escape(resolution.remark || "")}" placeholder="例如：差额 303 为尾差，财务确认可接受" />
          </label>
          <label class="ocw-voucher-resolution-confirm">
            <input type="checkbox" data-field="resolution_confirm" />
            <span>我确认按当前处理方式保存本次差异处理记录</span>
          </label>
          <div class="ocw-voucher-resolution-actions">
            <button class="ocw-primary-btn ocw-mini-btn" type="button" data-action="resolve-voucher-record" disabled>提交处理结果</button>
          </div>
        </div>
        ${savedHtml}
        ${historyHtml}
      </div>
    `;
  }

  async submitVoucherManualResolution(detailDialog, recordName) {
    const $wrapper = detailDialog.$wrapper;
    const action = $wrapper.find("[data-field='resolution_action']").val();
    const adjusted = String($wrapper.find("[data-field='adjusted_tax_total_mxn']").val() || "").trim();
    const remark = String($wrapper.find("[data-field='resolution_remark']").val() || "").trim();
    const confirmed = $wrapper.find("[data-field='resolution_confirm']").is(":checked");
    if (!confirmed) {
      frappe.msgprint("请先勾选确认后再提交处理结果。");
      return;
    }
    const doSave = async () => {
      const result = await this.call(
        "overseas_costing.api.import_api.resolve_tax_certificate_reconciliation",
        {
          record_name: recordName,
          resolution_action: action,
          adjusted_tax_total_mxn: adjusted,
          remark,
        },
        true
      );
      if (!result || !result.ok) {
        frappe.msgprint((result && result.message) || "保存人工处理结果失败。");
        return;
      }
      const $detail = $wrapper.find(".ocw-voucher-record-detail");
      $detail.replaceWith(this.renderTaxCertificateRecordDetail(result));
      if (this.activeVoucherParseDialog && this.activeVoucherParseDialog.$wrapper && this.activeVoucherParseDialog.$wrapper.is(":visible")) {
        this.loadTaxCertificateRecords(this.activeVoucherParseDialog).catch((error) => this.showError(error));
      }
      frappe.show_alert({ message: "处理结果已保存。", indicator: "green" });
    };
    frappe.confirm("确认保存这次完税凭证差异处理结果？", doSave);
  }

  renderVoucherPreview(dialog, result, state = "empty") {
    const $preview = dialog.$wrapper.find("[data-area='voucher-preview']");
    const $status = dialog.$wrapper.find("[data-area='voucher-preview-status']");
    $preview.removeClass("empty loading ready warn failed");
    this.updateVoucherPrimarySaveAction(dialog, false);
    if (state === "loading") {
      $status.text("正在上传并解析 PDF...");
      $preview.addClass("loading").text("解析中");
      return;
    }
    if (!result) {
      $status.text("选择文件后可先对比凭证字段。");
      $preview.addClass("empty").text("尚未对比");
      return;
    }

    const summary = result.summary || {};
    const header = result.header || {};
    const taxes = result.tax_totals || {};
    const items = result.line_items || [];
    const validation = result.validation || {};
    const validationStatus = validation.status || (summary.tax_total_matches_paid_total ? "passed" : "review");
    const statusText = validation.status_label || (summary.tax_total_matches_paid_total ? "通过" : "需复核");
    const statusClass = this.voucherValidationPreviewClass(validationStatus);
    const taxChips = this.renderVoucherTaxChips(taxes);
    const rows = items.slice(0, 30).map((row) => this.renderVoucherItemRow(row)).join("");
    const moreText = items.length > 30 ? `<div class="ocw-voucher-more">仅展示前 30 条，共 ${this.escape(String(items.length))} 条。</div>` : "";
    const declaredCount = summary.declared_item_count ?? "--";
    const validationHtml = this.renderVoucherValidation(validation);
    const reconciliation = result.reconciliation || {};
    if (result.saved_attachment_name) reconciliation.saved_attachment_name = result.saved_attachment_name;
    const reconciliationHtml = this.renderVoucherReconciliation(reconciliation, { showSaveButton: false });
    const reconciliationText = reconciliation.status_label ? `，对比${reconciliation.status_label}` : "";
    const canSave = Boolean(reconciliation.batch && reconciliation.batch.name);
    const paymentDateText = this.formatVoucherPaymentDate(header.payment_date || "");
    this.updateVoucherPrimarySaveAction(dialog, canSave);

    $status.text(`预览完成：校验${statusText}${reconciliationText}。`);
    $preview.addClass(statusClass).html(`
      <div class="ocw-voucher-validation-head ${this.escape(validationStatus)}">
        <div>
          <span>解析校验</span>
          <strong>${this.escape(statusText)}</strong>
        </div>
        <p>${this.escape(this.voucherValidationMessage(validationStatus))}</p>
      </div>
      <div class="ocw-voucher-summary">
        <div><span>报关单号</span><strong>${this.escape(header.pedimento_no || "--")}</strong></div>
        <div><span>凭证参考号</span><strong>${this.escape(header.pedimento_ref || header.pedimento_short_no || "--")}</strong></div>
        <div><span>柜号</span><strong>${this.escape(header.container_no || "--")}</strong></div>
        <div><span>支付日期</span><strong title="${this.escape(header.payment_date || "")}">${this.escape(paymentDateText)}</strong></div>
        <div><span>凭证原始汇率</span><strong>${this.escape(this.formatValue(header.exchange_rate || "--"))}</strong></div>
        <div><span>毛重 KG</span><strong>${this.escape(this.formatValue(header.gross_weight_kg || "--"))}</strong></div>
        <div><span>支付总额 MXN</span><strong>${this.escape(this.formatNumber(summary.paid_total_mxn || 0))}</strong></div>
        <div><span>商品分项</span><strong>${this.escape(String(summary.item_count || items.length || 0))} / ${this.escape(String(declaredCount))}</strong></div>
      </div>
      <div class="ocw-voucher-tax-chips">${taxChips}</div>
      ${reconciliationHtml}
      ${validationHtml}
      <div class="ocw-voucher-note">当前只做字段摘取预览；确认规则后再用于生成实际核算和多退少补对比。</div>
      <div class="ocw-voucher-table-wrap">
        <table class="ocw-voucher-table">
          <thead>
            <tr>
              <th>序号</th>
              <th>HS 编码</th>
              <th>海关进口名称</th>
              <th>数量</th>
              <th>IGI 税率</th>
              <th>IGI 税额</th>
              <th>IVA 税率</th>
              <th>IVA 税额</th>
            </tr>
          </thead>
          <tbody>${rows || `<tr><td colspan="8">未识别到商品分项</td></tr>`}</tbody>
        </table>
      </div>
      ${moreText}
    `);
  }

  updateVoucherPrimarySaveAction(dialog, canSave, label = "保存对比结果") {
    if (!dialog || !dialog.$wrapper) return;
    const $primary = dialog.get_primary_btn ? dialog.get_primary_btn() : dialog.$wrapper.find(".modal-footer .btn-primary");
    if (!$primary || !$primary.length) return;
    $primary.text(label).prop("disabled", !canSave).attr("title", canSave ? "保存解析快照到附件记录" : "请先解析并匹配到系统批次");
    if (canSave) {
      $primary.show();
    } else {
      $primary.hide();
    }
  }

  resetVoucherDialogAfterSave(dialog) {
    if (!dialog || !dialog.$wrapper) return;
    const $dropzone = dialog.$wrapper.find("[data-voucher-dropzone='1']");
    const $input = dialog.$wrapper.find(".ocw-voucher-file-input");
    dialog.$wrapper.removeData("ocw-voucher-file");
    dialog.$wrapper.removeData("ocw-voucher-upload");
    dialog.$wrapper.removeData("ocw-voucher-preview");
    $dropzone.removeClass("has-file is-dragover");
    dialog.$wrapper.find("[data-area='voucher-file-name']").text("拖放 PDF 到这里，或点击选择");
    if ($input.length) $input.val("");
    this.renderVoucherPreview(dialog, null, "empty");
    dialog.$wrapper.find("[data-area='voucher-preview-status']").text("保存完成，可继续上传下一份凭证。");
  }

  renderVoucherTaxChips(taxes = {}) {
    const rows = [
      ["海关手续费（DTA）", taxes.dta_mxn],
      ["预验证费（PRV）", taxes.prv_mxn],
      ["预验证增值税（PRV IVA）", taxes.prv_iva_mxn],
      ["进口关税（IGI/IGE）", taxes.igi_mxn],
      ["进口增值税（IVA）", taxes.iva_mxn],
    ];
    return `
      <div class="ocw-voucher-tax-title">税费构成 MXN</div>
      <div class="ocw-voucher-tax-grid">
        ${rows
          .map(
            ([label, value]) => `
              <div class="ocw-voucher-tax-item">
                <span>${this.escape(label)}</span>
                <strong>${this.escape(this.formatNumber(value || 0))}</strong>
              </div>
            `
          )
          .join("")}
      </div>
    `;
  }

  renderVoucherReconciliation(reconciliation, options = {}) {
    if (!reconciliation || !Object.keys(reconciliation).length) return "";
    const showSaveButton = options.showSaveButton !== false;
    const batch = reconciliation.batch || {};
    const voucher = reconciliation.voucher || {};
    const system = reconciliation.system || {};
    const diff = reconciliation.difference || {};
    const checks = reconciliation.checks || [];
    const status = reconciliation.status || "pending";
    const batchLabel = batch.customs_no || batch.waybill_no || batch.batch_no || batch.container_no || batch.name || "未匹配";
    const declaredCount = voucher.declared_item_count ?? voucher.item_count ?? "--";
    const checkRows = checks.map((check) => this.renderVoucherValidationRow(check)).join("");
    const saveButton = !showSaveButton
      ? ""
      : batch.name
        ? `<button class="ocw-primary-btn ocw-mini-btn" type="button" data-action="save-voucher-parse">${reconciliation.saved_attachment_name ? "已保存对比结果" : "保存对比结果"}</button>`
        : `<button class="ocw-primary-btn ocw-mini-btn" type="button" data-action="save-voucher-parse" disabled>保存对比结果</button>`;

    return `
      <div class="ocw-voucher-reconciliation ${this.escape(status)}">
        <div class="ocw-voucher-reconciliation-head">
          <div>
            <span>多退少补对比预览</span>
            <strong>${this.escape(reconciliation.status_label || "--")}</strong>
          </div>
          <div class="ocw-voucher-reconciliation-action">
            <p>${this.escape(reconciliation.message || "对比结果仅用于复核，不会自动写入成本。")}</p>
            ${saveButton}
          </div>
        </div>
        <div class="ocw-voucher-reconciliation-grid">
          <div><span>匹配批次</span><strong>${this.escape(batchLabel)}</strong></div>
          <div><span>凭证税费 MXN</span><strong>${this.escape(this.formatValidationValue(voucher.paid_total_mxn))}</strong></div>
          <div><span>系统税费 MXN</span><strong>${this.escape(this.formatValidationValue(system.system_import_tax_total_mxn))}</strong></div>
          <div><span>差额 MXN</span><strong>${this.escape(this.formatValidationValue(diff.tax_total_diff_mxn))}</strong></div>
          <div><span>差额方向</span><strong>${this.escape(diff.direction_label || "--")}</strong></div>
          <div><span>行数对比</span><strong>${this.escape(String(system.item_count || 0))} / ${this.escape(String(declaredCount))}</strong></div>
          <div><span>税费来源</span><strong>${this.escape(system.tax_source || "--")}</strong></div>
          <div><span>有税费行</span><strong>${this.escape(String(system.rows_with_tax_count || 0))}</strong></div>
        </div>
        ${
          checkRows
            ? `<table class="ocw-voucher-validation-table ocw-voucher-reconciliation-table">
                <thead>
                  <tr>
                    <th>项目</th>
                    <th>状态</th>
                    <th>说明</th>
                    <th>期望值</th>
                    <th>识别值</th>
                  </tr>
                </thead>
                <tbody>${checkRows}</tbody>
              </table>`
            : ""
        }
      </div>
    `;
  }

  renderVoucherValidation(validation) {
    const checks = (validation && validation.checks) || [];
    if (!checks.length) return "";
    const rows = checks.map((check) => this.renderVoucherValidationRow(check)).join("");
    return `
      <div class="ocw-voucher-validation-wrap">
        <div class="ocw-voucher-validation-title">
          <strong>校验明细</strong>
          <span>通过 ${this.escape(String(validation.passed_count || 0))} · 需复核 ${this.escape(String(validation.review_count || 0))} · 失败 ${this.escape(String(validation.failed_count || 0))}</span>
        </div>
        <table class="ocw-voucher-validation-table">
          <thead>
            <tr>
              <th>项目</th>
              <th>状态</th>
              <th>说明</th>
              <th>期望值</th>
              <th>识别值</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    `;
  }

  renderVoucherValidationRow(check) {
    const status = check.status || "review";
    return `
      <tr class="${this.escape(status)}">
        <td>${this.escape(check.label || "--")}</td>
        <td><span class="ocw-voucher-check-status ${this.escape(status)}">${this.escape(check.status_label || "--")}</span></td>
        <td>${this.escape(check.message || "--")}</td>
        <td>${this.escape(this.formatValidationValue(check.expected))}</td>
        <td>${this.escape(this.formatValidationValue(check.actual))}</td>
      </tr>
    `;
  }

  voucherValidationPreviewClass(status) {
    if (["failed", "unmatched", "exception"].includes(status)) return "failed";
    if (["review", "pending"].includes(status)) return "warn";
    return "ready";
  }

  voucherValidationMessage(status) {
    if (status === "failed") return "关键字段或金额不一致，不能直接用于最终核算，需要人工复核。";
    if (status === "review") return "基础解析已完成，但仍有字段需要人工确认。";
    return "基础字段、金额合计和分项数量已通过当前规则校验。";
  }

  formatValidationValue(value) {
    if (value === null || value === undefined || value === "") return "--";
    if (typeof value === "number") return this.formatNumber(value);
    if (Array.isArray(value)) return value.join("、");
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
  }

  normalizeVoucherPaymentDate(value) {
    const text = String(value || "").trim();
    if (!text) return "";
    const dateOnly = text.split(/\s+/)[0].replace(/[年月.]/g, "-").replace(/日/g, "");
    let match = dateOnly.match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$/);
    if (match) {
      const [, year, month, day] = match;
      return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    }
    match = dateOnly.match(/^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$/);
    if (match) {
      const [, day, month, year] = match;
      return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    }
    return text;
  }

  formatVoucherPaymentDate(rawDate, preferredDate = "") {
    const raw = String(rawDate || "").trim();
    const normalized = this.normalizeVoucherPaymentDate(preferredDate || raw);
    if (!normalized && !raw) return "--";
    if (!raw || raw === normalized) return normalized || raw;
    return `${normalized || raw}（原始：${raw}）`;
  }

  formatSystemPaymentFx(fxSync = {}, rawPaymentDate = "") {
    const hasFx = fxSync && (fxSync.action === "updated" || fxSync.action === "unchanged" || fxSync.usd_to_rmb || fxSync.rmb_to_mxn);
    if (!hasFx) {
      const message = fxSync.reason || fxSync.message || "未保存系统汇率；保存后优先按真实付款日查询，缺失时按付款审批完成日暂估。";
      return { heading: "系统采用汇率", title: message, lines: [message] };
    }

    const rateDate = this.normalizeVoucherPaymentDate(
      fxSync.normalized_fx_rate_date || fxSync.fx_rate_date || fxSync.normalized_payment_date || fxSync.payment_date || rawPaymentDate || ""
    );
    const sourceLabel = fxSync.fx_date_source_label || (fxSync.is_estimated_rate ? "付款审批完成日（暂估）" : "真实付款日");
    const heading = fxSync.is_estimated_rate ? "系统采用汇率（暂估）" : "系统采用汇率";
    const usdToRmb = this.numericOrNull(fxSync.usd_to_rmb);
    const rmbToMxn = this.numericOrNull(fxSync.rmb_to_mxn);
    const snapshotMxnRate = fxSync.rate_snapshots && fxSync.rate_snapshots.MXN
      ? this.numericOrNull(fxSync.rate_snapshots.MXN.cny_per_unit)
      : null;
    const mxnToRmb = this.numericOrNull(fxSync.fx_mxn_to_rmb) || snapshotMxnRate || (rmbToMxn ? 1 / rmbToMxn : null);
    const isFallbackRate = Boolean(fxSync.fallback_rate_source);
    const parts = [`${sourceLabel}：${rateDate || "未识别"}`];
    if (isFallbackRate) {
      parts.push(fxSync.fallback_message || "汇率库缺少付款日汇率，当前成本暂用版本汇率");
      parts.push(`汇率来源：${fxSync.fallback_rate_source_label || "当前版本汇率（暂用）"}`);
    } else if (fxSync.is_estimated_rate) {
      parts.push("后续拿到真实付款日后需重算确认");
    } else if (!fxSync.normalized_fx_rate_date && !fxSync.normalized_payment_date && !fxSync.rate_snapshots) {
      parts.push("历史保存汇率");
    }
    parts.push(`1 USD = ${usdToRmb ? this.formatNumber(usdToRmb) : "--"} RMB`);
    if (mxnToRmb && rmbToMxn) {
      parts.push(`1 MXN = ${this.formatNumber(mxnToRmb)} RMB（按 1 RMB = ${this.formatNumber(rmbToMxn)} MXN 换算）`);
    } else {
      parts.push(`1 MXN = ${mxnToRmb ? this.formatNumber(mxnToRmb) : "--"} RMB`);
    }
    return { heading, title: parts.join("；"), lines: parts };
  }

  numericOrNull(value) {
    if (value === null || value === undefined || value === "") return null;
    const number = Number(String(value).replace(/,/g, ""));
    return Number.isFinite(number) ? number : null;
  }

  renderVoucherItemRow(row) {
    const taxes = row.taxes || {};
    return `
      <tr>
        <td>${this.escape(row.row_no || "--")}</td>
        <td>${this.escape(row.hs_code || "--")}</td>
        <td title="${this.escape(row.import_name || "")}">${this.escape(row.import_name || "--")}</td>
        <td>${this.escape(this.formatValue(row.quantity_umc || "--"))}</td>
        <td>${this.escape(this.formatValue(taxes.igi_rate ?? "--"))}</td>
        <td>${this.escape(this.formatNumber(taxes.igi_amount_mxn || 0))}</td>
        <td>${this.escape(this.formatValue(taxes.iva_rate ?? "--"))}</td>
        <td>${this.escape(this.formatNumber(taxes.iva_amount_mxn || 0))}</td>
      </tr>
    `;
  }


  openOaLogisticsPullDialog() {
    const defaults = this.getDefaultPullDateRange();
    const dialog = new frappe.ui.Dialog({
      title: "拉取钉钉国际物流审批",
      fields: [
        {
          fieldtype: "HTML",
          fieldname: "pull_note",
          options: `
            <div class="ocw-pull-note">
              <strong>只补拉钉钉国际物流审批单</strong>
              <span>新单会创建批次，已有单据只更新追溯、附件、采购字段和明确费用，不会清空或删除已有批次。</span>
            </div>
          `,
        },
        { fieldtype: "Date", fieldname: "start", label: "开始日期", default: defaults.start_date, reqd: 1 },
        { fieldtype: "Date", fieldname: "end", label: "结束日期", default: defaults.end_date, reqd: 1 },
        {
          fieldtype: "Select",
          fieldname: "transport_modes",
          label: "运输方式",
          options: "全部\n海运\n空运\n快递",
          default: "全部",
        },
        {
          fieldtype: "Int",
          fieldname: "limit",
          label: "最多读取审批单数",
          default: 80,
          description: "默认读取近一个月内最多 80 条审批详情，避免一次拉取过多导致等待太久。",
        },
        {
          fieldtype: "HTML",
          fieldname: "pull_result",
          options: `<div class="ocw-pull-result empty" data-area="oa-pull-result">尚未开始拉取</div>`,
        },
      ],
      primary_action_label: "开始拉取",
      primary_action: async (values) => {
        await this.pullOaLogisticsApprovals(dialog, values || {});
      },
    });
    dialog.show();
    this.setOaPullPrimaryState(dialog, "ready");
  }

  async pullOaLogisticsApprovals(dialog, values) {
    if (dialog.$wrapper.data("ocw-pull-completed") && !values.force) {
      frappe.confirm("刚刚已经完成一次拉取，确认要按当前日期范围重新拉取吗？", () => {
        this.pullOaLogisticsApprovals(dialog, { ...values, force: true }).catch((error) => this.showError(error));
      });
      return;
    }
    const start = String(values.start || "").trim();
    const end = String(values.end || "").trim();
    if (!start || !end) {
      frappe.msgprint("请先选择开始日期和结束日期。");
      return;
    }
    dialog.$wrapper.data("ocw-pull-completed", false);
    this.setOaPullPrimaryState(dialog, "running");
    try {
      this.renderOaPullResult(dialog, null, "loading");
      const result = await this.call(
        "overseas_costing.api.import_api.pull_latest_oa_logistics_approvals",
        {
          start,
          end,
          transport_modes: this.normalizePullTransportMode(values.transport_modes),
          limit: Number(values.limit || 80) || 80,
        },
        true
      );
      this.renderOaPullResult(dialog, result, result.skipped ? "warn" : "ready");
      if (result.skipped) {
        this.setOaPullPrimaryState(dialog, "ready");
        frappe.show_alert({ message: result.reason || "钉钉拉取已跳过", indicator: "orange" });
        return;
      }
      const save = result.save || {};
      const message = `钉钉拉取完成：新增 ${save.created_count || 0}，更新 ${save.updated_count || 0}，已存在 ${save.unchanged_count || 0}，跳过 ${save.skipped_count || 0}`;
      this.recordUsage("DINGTALK_PULL", {
        remark: message,
        extra: { start, end, transport_modes: values.transport_modes || "ALL", limit: Number(values.limit || 80) || 80, save },
      });
      frappe.show_alert({ message, indicator: "green" });
      this.resetFilterValues();
      this.resetBatchScopeState();
      await this.loadBatches();
      dialog.$wrapper.data("ocw-pull-completed", true);
      this.setOaPullPrimaryState(dialog, "completed");
    } catch (error) {
      dialog.$wrapper.data("ocw-pull-completed", false);
      this.setOaPullPrimaryState(dialog, "ready");
      this.recordUsage("DINGTALK_PULL", {
        status: "Failed",
        remark: error.message || "钉钉拉取失败",
        extra: { start, end, transport_modes: values.transport_modes || "ALL" },
      });
      this.showError(error);
    }
  }

  async repullGapDingtalk(batchName = "") {
    const batch = this.findBatch(batchName || this.drawerBatchName || this.activeBatchName);
    if (!batch) return;
    const confirmed = await new Promise((resolve) => {
      frappe.confirm("确认重新拉取这票货的钉钉原单并刷新页面数据？", () => resolve(true), () => resolve(false));
    });
    if (!confirmed) return;
    try {
      const result = await this.call(
        "overseas_costing.api.import_api.refresh_oa_logistics_detail",
        {
          target: batch.name,
          limit: 50,
          include_non_sea: 1,
        },
        true
      );
      if (!result || result.ok === false) {
        throw new Error((result && result.message) || "钉钉原单刷新失败");
      }
      await this.refreshBatch(batch.name);
      await this.loadBatches();
      this.renderTable();
      if (this.drawerBatchName === batch.name) this.renderBatchDrawer();
      frappe.show_alert({ message: result.message || "钉钉原单已重新拉取", indicator: "green" });
    } catch (error) {
      this.showError(error);
    }
  }

  async openGapItemEdit(batchName = "", itemName = "", fieldname = "") {
    const batch = this.findBatch(batchName || this.drawerBatchName || this.activeBatchName);
    if (!batch) return;
    const items = this.batchItems[batch.name] || [];
    const row = items.find((item) => item.name === itemName);
    if (!row) {
      this.showPendingFeature("没有找到可补录的明细行。");
      return;
    }
    const targetField = fieldname || this.getItemEditableFieldForGap(batch.name, itemName, fieldname);
    if (!targetField) {
      this.showPendingFeature("当前明细没有可补录的字段。");
      return;
    }
    this.closeBatchDrawer({ updateUrl: false });
    await this.focusBatch(batch.name, { updateUrl: false });

    // focusBatch() rerenders the table, so locate the cell after rendering.
    const $target = this.$root
      .find("[data-editable-cell='1']")
      .filter((_, element) =>
        $(element).attr("data-batch-name") === batch.name &&
        $(element).attr("data-item-name") === itemName &&
        $(element).attr("data-fieldname") === targetField
      )
      .first();
    if (!$target.length) {
      this.showPendingFeature("没有找到可编辑的明细单元格，请先展开该批次。");
      return;
    }
    this.startCellEdit($target, null, true);
    const targetElement = $target.get(0);
    if (targetElement && typeof targetElement.scrollIntoView === "function") {
      targetElement.scrollIntoView({ behavior: "smooth", block: "center", inline: "center" });
    }
  }

  getItemEditableFieldForGap(batchName = "", itemName = "", preferredFieldname = "") {
    const items = this.batchItems[batchName] || [];
    const row = items.find((item) => item.name === itemName);
    if (!row) return "";
    if (preferredFieldname && this.isEditableColumn({ fieldname: preferredFieldname }) && Object.prototype.hasOwnProperty.call(row, preferredFieldname)) {
      return preferredFieldname;
    }
    const priorities = [
      "material_code",
      "product_name",
      "quantity",
      "actual_shipped_qty",
      "unit_price",
      "purchase_currency",
      "goods_value",
      "gross_weight_kg",
      "volume_m3",
      "chargeable_weight_kg",
      "china_to_mexico_freight_rmb",
      "mexico_customs_mxn",
      "mexico_customs_rmb",
      "mexico_customs_usd",
      "import_tax_total",
      "igi_amount",
      "iva_amount",
      "total_cost_rmb",
      "total_unit_rmb",
    ];
    return priorities.find((fieldname) => this.isEditableColumn({ fieldname }) && Object.prototype.hasOwnProperty.call(row, fieldname)) || "";
  }

  setOaPullPrimaryState(dialog, state = "ready") {
    const $button = dialog.get_primary_btn ? dialog.get_primary_btn() : dialog.$wrapper.find(".modal-footer .btn-primary");
    if (!$button || !$button.length) return;
    if (state === "running") {
      $button.prop("disabled", true).text("拉取中...");
      return;
    }
    $button.prop("disabled", false).text(state === "completed" ? "重新拉取" : "开始拉取");
  }

  renderOaPullResult(dialog, result, state = "empty") {
    const $target = dialog.$wrapper.find("[data-area='oa-pull-result']");
    $target.removeClass("empty loading ready warn");
    if (state === "loading") {
      $target.addClass("loading").text("正在拉取钉钉审批单并写入成本批次...");
      return;
    }
    if (!result) {
      $target.addClass("empty").text("尚未开始拉取");
      return;
    }
    if (result.skipped) {
      $target.addClass("warn").html(`<strong>本次未执行拉取</strong><span>${this.escape(result.reason || "缺少钉钉配置")}</span>`);
      return;
    }
    const pull = result.pull || {};
    const save = result.save || {};
    const counts = pull.transport_counts || {};
    const modeText = (result.transport_modes || []).map((mode) => this.transportLabel(mode)).join("、") || "全部";
    const writeCount = Number(save.created_count || 0) + Number(save.updated_count || 0);
    const completionText = writeCount
      ? "已写入最新变化，页面列表已刷新。"
      : "当前范围内审批单已在系统中，页面列表已刷新。";
    $target.addClass("ready").html(`
      <div class="ocw-pull-success-head">
        <strong>拉取完成</strong>
        <span>${this.escape(completionText)}需要再次执行时，请点击底部“重新拉取”。</span>
      </div>
      <div class="ocw-pull-result-grid">
        <div><span>日期范围</span><strong>${this.escape(result.start || "--")} 至 ${this.escape(result.end || "--")}</strong></div>
        <div><span>运输方式</span><strong>${this.escape(modeText)}</strong></div>
        <div><span>读取详情</span><strong>${this.escape(String(pull.detail_count || 0))}</strong></div>
        <div><span>命中国际物流</span><strong>${this.escape(String(pull.filtered_count || 0))}</strong></div>
        <div><span>新增批次</span><strong>${this.escape(String(save.created_count || 0))}</strong></div>
        <div><span>更新批次</span><strong>${this.escape(String(save.updated_count || 0))}</strong></div>
        <div><span>已存在</span><strong>${this.escape(String(save.unchanged_count || 0))}</strong></div>
        <div><span>跳过</span><strong>${this.escape(String(save.skipped_count || 0))}</strong></div>
      </div>
      <div class="ocw-pull-mode-counts">
        <span>海运 ${this.escape(String(counts.SEA || 0))}</span>
        <span>空运 ${this.escape(String(counts.AIR || 0))}</span>
        <span>快递 ${this.escape(String(counts.EXPRESS || 0))}</span>
      </div>
    `);
  }

  normalizePullTransportMode(value) {
    const text = String(value || "").trim();
    if (text === "海运") return "SEA";
    if (text === "空运") return "AIR";
    if (text === "快递") return "EXPRESS";
    return "ALL";
  }

  openImportDialog() {
    const dialog = new frappe.ui.Dialog({
      title: "导入/解析 Excel 附件",
      fields: [
        {
          fieldtype: "HTML",
          fieldname: "file_picker",
          options: `
            <div class="ocw-import-file-box">
              <label class="ocw-import-file-label">上传 Excel 文件</label>
              <div class="ocw-import-dropzone" data-import-dropzone="1" tabindex="0">
                <input class="ocw-import-file-input" type="file" accept=".xlsx,.xlsm" />
                <div class="ocw-import-drop-icon">XLSX</div>
                <div>
                  <strong data-area="import-file-name">拖放文件到这里，或点击选择</strong>
                  <span>支持 .xlsx / .xlsm</span>
                </div>
              </div>
              <div class="ocw-import-preview-actions">
                <button class="ocw-outline-btn ocw-mini-btn" type="button" data-action="preview-import">解析预览</button>
                <span data-area="import-preview-status">选择文件后可先预览，不会写入数据。</span>
              </div>
              <div class="ocw-import-preview empty" data-area="import-preview">尚未解析</div>
            </div>
          `,
        },
        {
          fieldtype: "Data",
          fieldname: "source_sheet",
          label: "工作表名称",
          default: "",
          description: "可留空自动识别。只有需要指定某个工作表时再填写 Excel 底部标签名。",
        },
        {
          fieldtype: "Check",
          fieldname: "include_double_clear",
          label: "包含双清/包税数据",
          default: 1,
        },
      ],
      primary_action_label: "导入",
      primary_action: async (values) => {
        const file = this.getImportDialogFile(dialog);
        if (!this.validateImportFile(file)) return;
        const uploaded = dialog.$wrapper.data("ocw-import-upload") || {};
        const imported = await this.importExcel({
          ...values,
          source_sheet: String(values.source_sheet || "").trim(),
          file: uploaded.file_url ? null : file,
          file_url: uploaded.file_url || null,
          source_name: uploaded.file_name || file.name,
        });
        if (imported) dialog.hide();
      },
    });
    dialog.show();
    this.bindImportDropzone(dialog);
  }

  bindImportDropzone(dialog) {
    const $dropzone = dialog.$wrapper.find("[data-import-dropzone='1']");
    const $input = dialog.$wrapper.find(".ocw-import-file-input");
    const $fileName = dialog.$wrapper.find("[data-area='import-file-name']");
    const setFile = (file) => {
      if (!file) return;
      dialog.$wrapper.data("ocw-import-file", file);
      dialog.$wrapper.removeData("ocw-import-upload");
      $fileName.text(file.name);
      $dropzone.addClass("has-file");
      this.renderImportPreview(dialog, null, "empty");
    };

    $dropzone.on("click keydown", (event) => {
      if (event.type === "keydown" && !["Enter", " "].includes(event.key)) return;
      event.preventDefault();
      $input.trigger("click");
    });
    $input.on("click", (event) => event.stopPropagation());
    $input.on("change", (event) => setFile(event.currentTarget.files?.[0]));
    $dropzone.on("dragenter dragover", (event) => {
      event.preventDefault();
      event.stopPropagation();
      $dropzone.addClass("is-dragover");
    });
    $dropzone.on("dragleave dragend drop", (event) => {
      event.preventDefault();
      event.stopPropagation();
      $dropzone.removeClass("is-dragover");
    });
    $dropzone.on("drop", (event) => {
      setFile(event.originalEvent?.dataTransfer?.files?.[0]);
    });
    dialog.$wrapper.on("click", "[data-action='preview-import']", (event) => {
      event.preventDefault();
      this.previewImportExcel(dialog).catch((error) => this.showError(error));
    });
  }

  getImportDialogFile(dialog) {
    return dialog.$wrapper.data("ocw-import-file") || dialog.$wrapper.find(".ocw-import-file-input").get(0)?.files?.[0] || null;
  }

  validateImportFile(file) {
    if (!file) {
      frappe.msgprint("请先上传 Excel 文件。");
      return false;
    }
    if (!this.isExcelFileRef(file.name || "")) {
      frappe.msgprint("请上传 .xlsx / .xlsm 格式的 Excel 文件。");
      return false;
    }
    return true;
  }

  async ensureImportFileUploaded(dialog, file) {
    const uploaded = dialog.$wrapper.data("ocw-import-upload");
    const sameFile =
      uploaded &&
      uploaded.file_url &&
      uploaded.source_file_name === file.name &&
      uploaded.source_file_size === file.size &&
      uploaded.source_file_modified === file.lastModified;
    if (sameFile) return uploaded;

    const uploadResult = await this.uploadImportFile(file);
    const normalized = {
      ...uploadResult,
      source_file_name: file.name,
      source_file_size: file.size,
      source_file_modified: file.lastModified,
    };
    dialog.$wrapper.data("ocw-import-upload", normalized);
    return normalized;
  }

  async previewImportExcel(dialog) {
    const file = this.getImportDialogFile(dialog);
    if (!this.validateImportFile(file)) return;

    const values = dialog.get_values() || {};
    this.renderImportPreview(dialog, null, "loading");
    const uploaded = await this.ensureImportFileUploaded(dialog, file);
    const result = await this.call(
      "overseas_costing.api.import_api.preview_yuewei_excel_file",
      {
        source_name: uploaded.file_name || file.name,
        file_url: uploaded.file_url,
        source_sheet: String(values.source_sheet || "").trim() || null,
        transport_keyword: "",
        include_double_clear: values.include_double_clear ? 1 : 0,
      },
      true
    );
    dialog.$wrapper.data("ocw-import-preview", result);
    this.renderImportPreview(dialog, result, "ready");
  }

  renderImportPreview(dialog, result, state = "empty") {
    const $preview = dialog.$wrapper.find("[data-area='import-preview']");
    const $status = dialog.$wrapper.find("[data-area='import-preview-status']");
    $preview.removeClass("empty loading ready warn");
    if (state === "loading") {
      $status.text("正在上传并解析文件...");
      $preview.addClass("loading").text("解析中");
      return;
    }
    if (!result) {
      $status.text("选择文件后可先预览，不会写入数据。");
      $preview.addClass("empty").text("尚未解析");
      return;
    }

    const parser = result.parser_meta || {};
    const selected = result.selected_summary || {};
    const source = result.source_summary || {};
    const batchIds = selected.batch_ids || [];
    const isEmpty = !Number(selected.block_count || 0);
    const visibleBatches = batchIds.slice(0, 5).map((batchId) => `<span>${this.escape(batchId)}</span>`).join("");
    const moreText = batchIds.length > 5 ? `<em>等 ${this.escape(String(batchIds.length))} 个</em>` : "";
    $status.text(isEmpty ? "已解析，但当前筛选未命中可导入批次。" : "预览完成，确认无误后点击导入。");
    $preview.addClass(isEmpty ? "warn" : "ready").html(`
      <div class="ocw-import-preview-grid">
        <div><span>工作表</span><strong>${this.escape(parser.sourceSheet || "--")}</strong></div>
        <div><span>解析器</span><strong>${this.escape(this.parserLabel(parser.parser))}</strong></div>
        <div><span>识别批次</span><strong>${this.escape(String(source.block_count || 0))}</strong></div>
        <div><span>命中批次</span><strong>${this.escape(String(selected.block_count || 0))}</strong></div>
        <div><span>SKU 行数</span><strong>${this.escape(String(selected.item_count || 0))}</strong></div>
      </div>
      <div class="ocw-import-preview-batches">${visibleBatches || "<span>无命中批次</span>"}${moreText}</div>
    `);
  }

  parserLabel(parserName) {
    const labels = {
      oa_attachment_detail: "国际物流附件",
      yuewei_cost_workbook: "成本总表",
    };
    return labels[parserName] || parserName || "--";
  }

  async importExcel(values) {
    try {
      let fileUrl = values.file_url || null;
      let sourceRef = values.source_name || (values.file ? values.file.name : values.file_url || values.file_path || "");
      if (values.file) {
        const uploadResult = await this.uploadImportFile(values.file);
        fileUrl = uploadResult.file_url || fileUrl;
        sourceRef = uploadResult.file_name || values.file.name || fileUrl || sourceRef;
      }
      const result = await this.call(
        "overseas_costing.api.import_api.import_yuewei_excel_file",
        {
          source_name: this.fileNameFromRef(sourceRef) || "Yuewei Excel",
          file_path: values.file_path || null,
          file_url: fileUrl,
          source_sheet: values.source_sheet || null,
          transport_keyword: "",
          include_double_clear: values.include_double_clear ? 1 : 0,
          fx_rmb_to_mxn: 2.6,
        },
        true
      );
      const selected = result.selected_summary || {};
      const importStats = this.summarizeImportResult(result);
      const parser = result.parser_meta || {};
      const parserHint = parser.sourceSheet ? `，工作表：${parser.sourceSheet}` : "";
      frappe.show_alert({
        message: `导入完成：${selected.block_count || 0} 个批次，${selected.item_count || 0} 行${parserHint}；${importStats}`,
        indicator: "green",
      });
      this.lastImportResult = result;
      this.resetFilterValues();
      await this.loadBatches();
      await this.focusImportedBatches(result, importStats);
      return true;
    } catch (error) {
      this.showError(error);
      return false;
    }
  }

  async uploadImportFile(file) {
    const formData = new FormData();
    formData.append("file", file, file.name);
    formData.append("is_private", "1");
    formData.append("folder", "Home");

    const response = await fetch("/api/method/upload_file", {
      method: "POST",
      body: formData,
      credentials: "same-origin",
      headers: {
        "X-Frappe-CSRF-Token": frappe.csrf_token || "",
      },
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || data.exc) {
      throw new Error(this.extractServerMessage(data) || "Excel 文件上传失败");
    }
    const message = data.message || data;
    if (!message.file_url) {
      throw new Error("Excel 文件已上传，但没有返回文件地址。");
    }
    return message;
  }

  extractServerMessage(data) {
    if (!data) return "";
    if (typeof data === "string") {
      try {
        return this.extractServerMessage(JSON.parse(data));
      } catch (_error) {
        return data;
      }
    }
    if (data.message && typeof data.message === "string") return data.message;
    if (data._server_messages) {
      try {
        const messages = JSON.parse(data._server_messages).map((item) => {
          try {
            const parsed = JSON.parse(item);
            return parsed.message || item;
          } catch (_error) {
            return item;
          }
        });
        return messages.join("；");
      } catch (_error) {
        return String(data._server_messages);
      }
    }
    if (data.exception) return String(data.exception);
    if (data.exc) return String(data.exc);
    if (data.statusText) return String(data.statusText);
    return "";
  }

  fileNameFromRef(value) {
    const text = String(value || "").trim();
    if (!text) return "";
    const clean = text.split("?")[0];
    const name = clean.split(/[\\/]/).filter(Boolean).pop() || clean;
    try {
      return decodeURIComponent(name);
    } catch (_error) {
      return name;
    }
  }

  summarizeImportResult(result) {
    const batches = result.created_batches || [];
    if (!batches.length) return "未写入新数据";
    const batchCreated = batches.filter((row) => row.batch_action === "created").length;
    const batchUpdated = batches.filter((row) => row.batch_action === "updated").length;
    const itemCreated = batches.reduce((total, row) => total + Number(row.created_item_count || 0), 0);
    const itemUpdated = batches.reduce((total, row) => total + Number(row.updated_item_count || 0), 0);
    const itemUnchanged = batches.reduce((total, row) => total + Number(row.unchanged_item_count || 0), 0);
    return `批次新增 ${batchCreated} / 更新 ${batchUpdated}，明细新增 ${itemCreated} / 更新 ${itemUpdated} / 未变 ${itemUnchanged}`;
  }

  importedBatchNames(result) {
    return (result.created_batches || []).map((row) => row.batch_name).filter(Boolean);
  }

  importedBatchLabels(result) {
    return (result.created_batches || [])
      .map((row) => row.batch_no || row.batch_name)
      .filter(Boolean);
  }

  async focusImportedBatches(result, statsText = "") {
    const batchNames = this.importedBatchNames(result);
    if (!batchNames.length) {
      this.updateSearchResult();
      return;
    }

    const imported = new Set(batchNames);
    this.lastImportedBatchNames = imported;
    this.visibleBatches = this.batches.slice();
    await this.prefetchBatchItems(this.visibleBatches);
    this.expandedBatchNames = new Set(this.visibleBatches.filter((batch) => imported.has(batch.name)).map((batch) => batch.name));

    const activeBatch = this.visibleBatches.find((batch) => imported.has(batch.name));
    if (activeBatch) {
      this.activeBatchName = activeBatch.name;
      await this.loadAuditLogs(activeBatch.name, activeBatch.current_version);
    }

    this.renderTable();
    this.renderImportResult(result, statsText);
  }

  renderImportResult(result, statsText = "") {
    const labels = this.importedBatchLabels(result);
    const visibleLabels = labels.slice(0, 3).join("、");
    const suffix = labels.length > 3 ? `等 ${labels.length} 个批次` : "";
    const selected = result.selected_summary || {};
    const message = `本次导入：${selected.block_count || labels.length || 0} 个批次，${selected.item_count || 0} 行 SKU；${statsText || this.summarizeImportResult(result)}。已在完整列表中展开 ${visibleLabels}${suffix}`;
    this.$root.find("[data-area='search-result']").removeClass("empty").addClass("active imported").text(message);
  }

  renderRecalculateResult(batchName, summary = {}) {
    const batch = this.findBatch(batchName) || this.getVisibleActiveBatch();
    const label = batch ? batch.waybill_no || batch.batch_no || batch.name : batchName;
    const ai = summary.ai_allocation || {};
    const aiText = ai.ok
      ? `AI基础分摊：已填入（${ai.model || "DeepSeek"}）`
      : `AI基础分摊：${ai.message || "未生成，已使用系统基础规则"}`;
    const parts = [
      `批次 ${label || "--"}`,
      `SKU ${this.formatValue(summary.item_count || 0)} 行`,
      `总货值 ${this.formatNumber(summary.total_goods_value || 0)} RMB`,
      `毛重 ${this.formatNumber(summary.total_gross_weight_kg || 0)} KG`,
      `综合成本 ${this.formatNumber(summary.total_cost_rmb || 0)} RMB`,
      `规则 ${this.formatValue(summary.rule_count || 0)} 条`,
      aiText,
    ];
    this.$root
      .find("[data-area='search-result']")
      .removeClass("empty imported")
      .addClass("active calculated")
      .text(`试算完成：${parts.join("；")}`);
  }

  async openCategoryPreviewDialog(batchName = "") {
    const selectableBatches = this.getSelectableBatches();
    const batch = this.getSelectableBatch(batchName, selectableBatches);
    if (!batch) {
      this.showPendingFeature("当前没有可归类的批次，请先拉取或查询一条数据。");
      return;
    }
    this.activeBatchName = batch.name;
    const batchOptions = this.renderSelectableBatchOptions(batch.name, selectableBatches);
    const batchSelectDisabled = selectableBatches.length ? "" : " disabled";

    const dialog = new frappe.ui.Dialog({
      title: "AI 商品业务归类预览",
      fields: [
        {
          fieldtype: "HTML",
          fieldname: "category_preview",
          options: `
            <div class="ocw-category-toolbar">
              <label>
                <span>当前批次</span>
                <select class="form-control ocw-batch-select" data-role="category-batch-select" aria-label="选择商品归类批次"${batchSelectDisabled}>${batchOptions}</select>
              </label>
              <em>${this.escape(this.scopedBatchHint())}</em>
            </div>
            <div class="ocw-category-preview" data-area="category-preview">
              <div class="ocw-category-loading">正在检查当前批次是否存在可建议的业务大类...</div>
            </div>
          `,
        },
      ],
      primary_action_label: "关闭",
      primary_action: () => dialog.hide(),
    });
    dialog.show();
    dialog.$wrapper.addClass("ocw-category-modal");
    dialog.$wrapper.data("ocw-category-batch-name", batch.name);
    dialog.$wrapper.on("change", "[data-role='category-batch-select']", (event) => {
      const selectedBatch = this.findSelectableBatch(String($(event.currentTarget).val() || ""));
      if (!selectedBatch) return;
      this.activeBatchName = selectedBatch.name;
      dialog.$wrapper.data("ocw-category-batch-name", selectedBatch.name);
      this.loadCategoryPreview(dialog, selectedBatch).catch((error) => {
        dialog.hide();
        this.showError(error);
      });
    });
    this.loadCategoryPreview(dialog, batch).catch((error) => {
      dialog.hide();
      this.showError(error);
    });
  }

  async loadCategoryPreview(dialog, batch) {
    dialog.$wrapper.find("[data-area='category-preview']").html(`
      <div class="ocw-category-loading">正在检查当前批次是否存在可建议的业务大类...</div>
    `);
    const result = await this.call(
      "overseas_costing.api.category.preview_batch_categories",
      {
        batch_name: batch.name,
        version_name: batch.current_version,
        limit: 500,
      },
      true
    );
    this.renderCategoryPreview(dialog, result, batch);
  }

  renderCategoryPreview(dialog, result, batch) {
    const $target = dialog.$wrapper.find("[data-area='category-preview']");
    if (!result || !result.ok) {
      $target.html(`
        <div class="ocw-category-empty">
          <strong>暂时无法生成商品归类预览</strong>
          <span>${this.escape((result && result.message) || "请确认当前批次已有物料明细。")}</span>
        </div>
      `);
      return;
    }

    const items = result.items || [];
    const summary = result.summary || {};
    const categoryCounts = summary.category_counts || {};
    const countChips = Object.keys(categoryCounts)
      .map((name) => `<span>${this.escape(name)} ${this.escape(String(categoryCounts[name]))}</span>`)
      .join("");
    const rows = items.map((row) => this.renderCategoryPreviewRow(row)).join("");
    const batchLabel = batch.waybill_no || batch.batch_no || batch.name;

    $target.html(`
      <div class="ocw-category-summary">
        <div><span>当前批次</span><strong>${this.escape(batchLabel || "--")}</strong></div>
        <div><span>物料行数</span><strong>${this.escape(String(summary.item_count || items.length || 0))}</strong></div>
        <div><span>归类候选</span><strong>${this.escape(String(summary.business_category_candidate_count || summary.normalization_candidate_count || 0))}</strong></div>
        <div><span>AI命中</span><strong>${this.escape(String(summary.ai_business_category_count || summary.ai_normalization_count || 0))}</strong></div>
        <div><span>无需处理</span><strong>${this.escape(String(summary.no_action_count || 0))}</strong></div>
        <div><span>影响税费</span><strong>不影响</strong></div>
      </div>
      <div class="ocw-category-note">
        AI 用于把不同语言、不同写法的商品归到统一业务大类，辅助查询、汇总和分摊参考；不会修改海关进口名称、HS 编码、税率和完税金额。
      </div>
      <div class="ocw-category-counts">${countChips || "<span>当前批次没有明确的归类候选</span>"}</div>
      <div class="ocw-category-table-wrap">
        <table class="ocw-category-table">
          <thead>
            <tr>
              <th>物料编码</th>
              <th>中文品名</th>
              <th>海关进口名称</th>
              <th>规格型号<br>Especificación / Modelo</th>
              <th>建议业务大类</th>
              <th>状态</th>
              <th>原因</th>
            </tr>
          </thead>
          <tbody>${rows || `<tr><td colspan="7">当前批次暂无物料明细</td></tr>`}</tbody>
        </table>
      </div>
    `);
  }

  renderCategoryPreviewRow(row) {
    const status = this.categoryStatusInfo(row);
    return `
      <tr class="${this.escape(status.rowClass)}">
        <td>${this.escape(row.material_code || "--")}</td>
        <td title="${this.escape(row.product_name || "")}">${this.escape(row.product_name || "--")}</td>
        <td title="${this.escape(row.import_name || "")}">${this.escape(row.import_name || "--")}</td>
        <td title="${this.escape(row.spec_model || "")}">${this.escape(row.spec_model || "--")}</td>
        <td><strong>${this.escape(row.suggested_business_category || row.suggested_name || "--")}</strong></td>
        <td><span class="ocw-category-status ${this.escape(status.className)}">${this.escape(status.label)}</span></td>
        <td title="${this.escape(row.reason || "")}">${this.escape(row.reason || "--")}</td>
      </tr>
    `;
  }

  categoryStatusInfo(row) {
    if (row.needs_review) {
      if (row.ai_ready || row.match_type === "ai_business_category" || row.match_type === "ai_name_normalization") {
        return { label: "AI候选", className: "ai", rowClass: "needs-ai" };
      }
      return { label: "待确认", className: "review", rowClass: "needs-review" };
    }
    return { label: "无需归类", className: "noop", rowClass: "" };
  }

  formatConfidence(value) {
    const number = Number(value);
    if (!Number.isFinite(number) || number <= 0) return "--";
    const normalized = number > 1 ? number / 100 : number;
    return `${Math.round(normalized * 100)}%`;
  }

  isExcelFileRef(value) {
    const text = String(value || "").split("?")[0].toLowerCase();
    return text.endsWith(".xlsx") || text.endsWith(".xlsm");
  }

  isPdfFileRef(value) {
    const text = String(value || "").split("?")[0].toLowerCase();
    return text.endsWith(".pdf");
  }

  isImageFileRef(value) {
    const text = String(value || "").split("?")[0].toLowerCase();
    return [".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"].some((suffix) => text.endsWith(suffix));
  }


  isWordFileRef(value) {
    const text = String(value || "").split("?")[0].toLowerCase();
    return text.endsWith(".doc") || text.endsWith(".docx");
  }

  isTextFileRef(value) {
    return String(value || "").split("?")[0].toLowerCase().endsWith(".txt");
  }

  openPurchasePreviewDialog(batchName = "") {
    const batch = batchName ? this.findBatch(batchName) : this.getActiveBatch();
    if (!batch) {
      this.showPendingFeature("当前没有可预览的批次。");
      return;
    }
    this.activeBatchName = batch.name;
    const batchLabel = batch.waybill_no || batch.batch_no || batch.name;
    const dialog = new frappe.ui.Dialog({
      title: "采购支出 OA 预览",
      fields: [
        {
          fieldtype: "HTML",
          fieldname: "purchase_preview",
          options: `
            <div class="ocw-purchase-preview" data-area="purchase-preview">
              <div class="ocw-purchase-loading">正在读取关联采购审批</div>
            </div>
          `,
        },
      ],
      primary_action_label: "关闭",
      primary_action: () => dialog.hide(),
    });
    dialog.show();
    this.activeOaAttachmentDialog = dialog;
    dialog.$wrapper.addClass("ocw-purchase-modal");
    dialog.$wrapper.find("[data-area='purchase-preview']").html(`
      <div class="ocw-purchase-target">
        <span>当前批次</span>
        <strong>${this.escape(batchLabel)}</strong>
        <em>正在读取关联采购支出单，用于跳转原单并同步 OA 采购字段。</em>
      </div>
      <div class="ocw-purchase-loading">正在读取关联采购审批</div>
    `);
    this.previewPurchaseExpense(batch, dialog).catch((error) => {
      dialog.$wrapper.find("[data-area='purchase-preview']").html(`
        <div class="ocw-purchase-empty">
          <strong>采购支出单读取失败</strong>
          <span>${this.escape(this.normalizeErrorMessage(error))}</span>
        </div>
      `);
    });
  }

  async previewPurchaseExpense(batch, dialog) {
    const result = await this.call(
      "overseas_costing.api.import_api.preview_linked_purchase_expense_oa",
      {
        batch_name: batch.name,
        version_name: batch.current_version || null,
      },
      true
    );
    this.renderPurchasePreview(dialog, result, batch);
  }

  renderPurchasePreview(dialog, result, batch) {
    const $target = dialog.$wrapper.find("[data-area='purchase-preview']");
    if (!result || !result.ok) {
      $target.html(`
        <div class="ocw-purchase-empty">
          <strong>暂时无法读取采购支出单</strong>
          <span>${this.escape((result && result.message) || "请确认当前批次已经从国际物流 OA 关联采购支出审批。")}</span>
        </div>
      `);
      return;
    }

    const preview = result.writeback_preview || {};
    const matchedRows = preview.matched_rows || [];
    const writableRows = matchedRows.filter((row) =>
      (row.business_changes || []).some((change) => ["fillable", "conflict"].includes(change.status))
    );
    const batchLabel = result.batch_no || batch.waybill_no || batch.batch_no || batch.name;
    const linkedHtml = this.renderPurchaseSourceList(result.purchase_summaries || []);

    $target.html(`
      <div class="ocw-purchase-target">
        <span>当前批次</span>
        <strong>${this.escape(batchLabel)}</strong>
        <em>这里只显示关联采购支出单；采购字段按 OA 明细同步写入系统。</em>
      </div>
      <div class="ocw-purchase-note">
        ${linkedHtml || "当前没有读取到关联采购支出审批。"}
      </div>
      ${this.renderPurchaseApplyAction(preview, writableRows, result)}
    `);
    dialog.$wrapper
      .off("click.ocwPurchase")
      .on("click.ocwPurchase", "[data-action='apply-purchase-fillable']", () => {
        this.applyPurchaseFillableFields(batch, dialog, preview).catch((error) => this.showError(error));
      })
      .on("click.ocwPurchase", "[data-action='open-purchase-source']", (event) => {
        this.openDingtalkLink($(event.currentTarget).attr("data-open-url"));
      });
  }

  renderPurchaseSourceList(rows) {
    if (!rows.length) return "";
    return `
      <div class="ocw-purchase-source-list">
        ${rows
          .map((row) => {
            const title = row.approval_title || "采购支出审批";
            const approvalNo = row.source_approval_no || "--";
            const approvalStatus = String(row.approval_status || "").trim();
            const approvalInvalid =
              this.isInvalidApprovalStatusText(approvalStatus) ||
              this.isInvalidApprovalStatusText(row.message);
            const statusHtml = approvalInvalid
              ? `<span class="ocw-purchase-source-status is-invalid">采购审批无效${approvalStatus ? `：${this.escape(approvalStatus)}` : ""}</span>`
              : approvalStatus
                ? `<span class="ocw-purchase-source-status">${this.escape(approvalStatus)}</span>`
                : "";
            const meta = `${row.purchase_currency || "--"} · ${row.detail_row_count || 0} 行`;
            const button = row.can_open
              ? `<a class="ocw-link-btn" href="${this.escape(row.open_url || "")}" target="_blank" rel="noopener noreferrer">打开原单</a>`
              : `<span class="ocw-purchase-source-disabled">无链接</span>`;
            return `
              <div class="ocw-purchase-source-row">
                <div>
                  <strong>${this.escape(approvalNo)}</strong>
                  <span title="${this.escape(title)}">${this.escape(title)}</span>
                  ${statusHtml}
                  <em>${this.escape(meta)}</em>
                </div>
                ${button}
              </div>
            `;
          })
          .join("")}
      </div>
    `;
  }

  renderPurchaseApplyAction(preview, writableRows = [], result = {}) {
    const writableCount = Number((preview && preview.writable_row_count) || writableRows.length || 0);
    if (!writableCount) return "";
    const linkedCount = Number(result.linked_purchase_count || result.purchase_summary_count || 0);
    const detailCount = Number(result.mapped_purchase_row_count || 0);
    return `
      <div class="ocw-purchase-apply">
        <div>
          <strong>同步采购字段到系统</strong>
          <span>已读取 ${this.escape(String(linkedCount))} 个采购支出单、${this.escape(String(detailCount))} 行明细；按物料编码写入单价Precio、币种Moneda、总金额Monto Total。</span>
        </div>
        <button class="ocw-primary-btn ocw-mini-btn" data-action="apply-purchase-fillable">同步采购字段</button>
      </div>
    `;
  }

  async applyPurchaseFillableFields(batch, dialog, preview) {
    if (!batch || this.isApplyingPurchaseFill) return;
    const writableCount = Number((preview && preview.writable_row_count) || 0);
    if (!writableCount) {
      frappe.show_alert({ message: "当前没有可写入的采购字段", indicator: "blue" });
      return;
    }

    this.isApplyingPurchaseFill = true;
    const $button = dialog.$wrapper.find("[data-action='apply-purchase-fillable']");
    $button.prop("disabled", true).text("同步中");
    try {
      const result = await this.call(
        "overseas_costing.api.import_api.apply_linked_purchase_expense_fillable_fields",
        {
          batch_name: batch.name,
          version_name: batch.current_version || null,
        },
        true
      );
      if (!result.ok) {
        throw new Error(result.message || "采购字段同步失败");
      }
      if (Number(result.updated_count || 0) > 0) {
        this.markBatchDirty(batch.name);
      }
      await this.loadBatchItems(batch.name, batch.current_version, true);
      await this.loadAuditLogs(batch.name, batch.current_version);
      this.expandedBatchNames.add(batch.name);
      this.renderTable();
      this.renderDiffPanel();
      frappe.show_alert({ message: result.message || "采购字段已同步", indicator: result.updated_count ? "green" : "blue" });
      dialog.hide();
    } finally {
      this.isApplyingPurchaseFill = false;
      $button.prop("disabled", false).text("同步采购字段");
    }
  }

  openApprovalSourceDialog(batchName = "") {
    const batch = batchName ? this.findBatch(batchName) : this.getActiveBatch();
    if (!batch) {
      this.showPendingFeature("当前没有可查看审批单来源的批次。");
      return;
    }
    this.activeBatchName = batch.name;
    const batchLabel = batch.batch_no || batch.waybill_no || batch.name;
    const dialog = new frappe.ui.Dialog({
      title: "审批单与 OA 来源",
      fields: [
        {
          fieldtype: "HTML",
          fieldname: "approval_source",
          options: `
            <div class="ocw-quick-panel">
              <div class="ocw-quick-context">
                <span>当前批次</span>
                <strong>${this.escape(batchLabel)}</strong>
              </div>
              <button class="ocw-quick-card" data-action="approval-open-original">
                <strong>钉钉原单</strong>
                <span>打开当前批次对应的钉钉审批表</span>
              </button>
            </div>
          `,
        },
      ],
      primary_action_label: "关闭",
      primary_action: () => dialog.hide(),
    });
    dialog.show();
    dialog.$wrapper.addClass("ocw-quick-modal");
    dialog.$wrapper
      .off("click.ocwApprovalSource")
      .on("click.ocwApprovalSource", "[data-action='approval-open-original']", () => {
        this.openDingtalkOrder(batch.name);
      });
  }

  openSourceCenterDialog(batchName = "", gap = {}) {
    const batch = batchName ? this.findBatch(batchName) : this.getActiveBatch();
    if (!batch) {
      this.showPendingFeature("当前没有可查看资料的批次。");
      return;
    }
    this.activeBatchName = batch.name;
    const logisticsType = this.detectManualDocumentLogisticsType(batch);
    const focus = {
      fieldname: String(gap.fieldname || "").trim(),
      label: String(gap.label || gap.fieldname || "").trim(),
    };
    const focusSlotCodes = this.manualDocumentSlotsForGap(batch, focus, logisticsType);
    const dialog = new frappe.ui.Dialog({
      title: focus.label ? `补齐资料：${focus.label}` : "资料上传与补齐",
      size: "large",
      fields: [
        {
          fieldtype: "HTML",
          fieldname: "manual_documents",
          options: `<div data-area="manual-documents">${this.renderManualDocumentPanel(batch, logisticsType, [], { ...focus, slotCodes: focusSlotCodes })}</div>`,
        },
      ],
      primary_action_label: "关闭",
      primary_action: () => dialog.hide(),
    });
    dialog.show();
    dialog.$wrapper.addClass("ocw-purchase-modal ocw-manual-document-modal");
    this.addManualDocumentBatchParseButton(batch, dialog);
    dialog.$wrapper
      .off("click.ocwManualDocuments")
      .on("click.ocwManualDocuments", "[data-action='manual-doc-logistics']", (event) => {
        const nextType = $(event.currentTarget).attr("data-logistics-type");
        this.loadManualDocumentAttachments(batch, dialog, nextType, { ...focus, slotCodes: this.manualDocumentSlotsForGap(batch, focus, nextType) }).catch((error) => this.showError(error));
      })
      .on("click.ocwManualDocuments", "[data-action='manual-fill-gap']", (event) => {
        const $button = $(event.currentTarget);
        const currentFocusSlotCodes = dialog.$wrapper
          .find(".ocw-manual-doc-card.is-gap-focus")
          .map((index, element) => $(element).attr("data-slot-code"))
          .get()
          .filter(Boolean);
        const clickedSlotCode = $button.attr("data-slot-code") || "";
        this.openManualGapFillDialog(
          batch,
          {
            fieldname: $button.attr("data-gap-fieldname") || focus.fieldname,
            label: $button.attr("data-gap-label") || focus.label,
            slotCode: clickedSlotCode,
            slotCodes: currentFocusSlotCodes.length ? currentFocusSlotCodes : clickedSlotCode ? [clickedSlotCode] : [],
            slotLabel: $button.attr("data-slot-label") || "",
            attachmentType: $button.attr("data-attachment-type") || "Other",
            required: $button.attr("data-required") === "1",
            logisticsType: $button.attr("data-logistics-type") || logisticsType,
          },
          dialog
        );
      })
      .on("click.ocwManualDocuments", "[data-action='upload-manual-document']", (event) => {
        const $button = $(event.currentTarget);
        const slot = {
          code: $button.attr("data-slot-code"),
          label: $button.attr("data-slot-label"),
          attachmentType: $button.attr("data-attachment-type"),
          required: $button.attr("data-required") === "1",
          focusSlotCodes: dialog.$wrapper
            .find(".ocw-manual-doc-card.is-gap-focus")
            .map((index, element) => $(element).attr("data-slot-code"))
            .get()
            .filter(Boolean),
        };
        const activeType = $button.attr("data-logistics-type");
        this.openManualDocumentUploader(batch, dialog, activeType, slot);
      })
      .on("click.ocwManualDocuments", "[data-action='preview-manual-document']", (event) => {
        const $button = $(event.currentTarget);
        this.openOaAttachmentFilePreviewDialog($button.attr("data-file-url"), $button.attr("data-file-name"));
      })
      .on("click.ocwManualDocuments", "[data-action='download-manual-document']", (event) => {
        const $button = $(event.currentTarget);
        this.downloadFileToLocal($button.attr("data-file-url"), $button.attr("data-file-name"));
      })
      .on("click.ocwManualDocuments", "[data-action='delete-manual-document']", (event) => {
        const focusSlotCodes = dialog.$wrapper
          .find(".ocw-manual-doc-card.is-gap-focus")
          .map((index, element) => $(element).attr("data-slot-code"))
          .get()
          .filter(Boolean);
        this.deleteManualDocumentAttachment(
          batch,
          dialog,
          $(event.currentTarget).attr("data-attachment-name"),
          $(event.currentTarget).attr("data-logistics-type"),
          { fieldname: focus.fieldname, label: focus.label, slotCodes: focusSlotCodes }
        ).catch((error) => this.showError(error));
      });
    this.loadManualDocumentAttachments(batch, dialog, logisticsType, { ...focus, slotCodes: focusSlotCodes }).catch((error) => this.showError(error));
  }

  manualDocumentSlotsForGap(batch = {}, gap = {}, logisticsType = "") {
    const resolvedType = logisticsType || this.detectManualDocumentLogisticsType(batch);
    const plan = this.manualDocumentPlans(resolvedType);
    const fieldname = String(gap.fieldname || "").trim().toLowerCase();
    const label = String(gap.label || "").trim().toLowerCase();
    const haystack = `${fieldname} ${label}`;
    const codes = (predicate) => plan.filter(predicate).map((slot) => slot.code);
    const first = (predicate) => codes(predicate)[0] || "";

    if (
      fieldname === "actual_shipped_qty" ||
      haystack.includes("actual_shipped") ||
      haystack.includes("outbound") ||
      haystack.includes("出库") ||
      haystack.includes("实际发货") ||
      haystack.includes("发货数量")
    ) {
      return codes((slot) => slot.code.includes("packing_list") || slot.code === "express_goods_list");
    }
    if (haystack.includes("customs") || haystack.includes("报关") || haystack.includes("海关")) {
      return codes((slot) => slot.code.includes("customs_declaration"));
    }
    if (haystack.includes("waybill") || haystack.includes("bill") || haystack.includes("运单") || haystack.includes("提单")) {
      return codes((slot) => slot.code.includes("waybill") || slot.code.includes("bill_of_lading") || slot.code === "express_bill");
    }
    if (haystack.includes("freight") || haystack.includes("logistics") || haystack.includes("运输") || haystack.includes("运费") || haystack.includes("物流")) {
      return codes((slot) => slot.oaSource || slot.code.includes("forwarder_bill") || slot.code === "express_bill");
    }
    if (haystack.includes("clearance") || haystack.includes("清关")) {
      return codes((slot) => slot.code.includes("clearance_fee") || slot.code.includes("forwarder_bill") || slot.code === "express_bill");
    }
    if (haystack.includes("tariff") || haystack.includes("duty") || haystack.includes("tax") || haystack.includes("关税") || haystack.includes("税费")) {
      return codes((slot) => slot.code.includes("tax_certificate") || slot.code.includes("clearance_fee"));
    }
    if (
      haystack.includes("subsidiary") ||
      haystack.includes("business") ||
      haystack.includes("主体") ||
      haystack.includes("公司") ||
      fieldname.includes("source_")
    ) {
      return codes((slot) => slot.oaSource);
    }
    const fallback = first((slot) => slot.code.endsWith("_other")) || plan[0]?.code;
    return fallback ? [fallback] : [];
  }

  manualDocumentSlotForGap(batch = {}, gap = {}, logisticsType = "") {
    return this.manualDocumentSlotsForGap(batch, gap, logisticsType)[0] || "";
  }

  addManualDocumentBatchParseButton(batch, dialog) {
    const $footer = dialog.$wrapper.find(".modal-footer");
    if (!$footer.length || $footer.find("[data-action='manual-doc-batch-parse']").length) return;
    const $button = $(
      '<button class="btn btn-secondary btn-sm ocw-manual-batch-parse-btn" type="button" data-action="manual-doc-batch-parse">批量解析</button>'
    );
    $button.on("click", () => {
      this.parseManualDocumentAttachments(batch, dialog, $button).catch((error) => this.showError(error));
    });
    const $primary = $footer.find(".btn-primary").last();
    if ($primary.length) {
      $button.insertBefore($primary);
    } else {
      $footer.append($button);
    }
  }

  detectManualDocumentLogisticsType(batch = {}) {
    const mode = String(batch.transport_mode || "").toUpperCase();
    if (["AIR", "AIR_FREIGHT"].includes(mode)) return "AIR";
    if (["EXPRESS", "COURIER", "DOUBLE_CLEAR"].includes(mode)) return "EXPRESS";
    return "SEA";
  }

  manualDocumentLogisticsTabs() {
    return [
      { value: "SEA", label: "海运" },
      { value: "AIR", label: "空运" },
      { value: "EXPRESS", label: "快递" },
    ];
  }

  manualDocumentPlans(logisticsType = "SEA") {
    const plans = {
      SEA: [
        { code: "sea_approval_attachment", label: "国际物流 OA 附件", required: false, oaSource: true, attachmentType: "Other", purpose: "系统优先从钉钉读取；缺失或需复核时再补传" },
        { code: "sea_customs_declaration", label: "报关资料", required: true, attachmentType: "Customs Declaration", purpose: "报关单号、海关编码、申报品名、申报数量" },
        { code: "sea_packing_list", label: "装箱单", required: true, attachmentType: "Packing List", purpose: "物料、数量、重量、体积、箱规" },
        { code: "sea_commercial_invoice", label: "商业发票", required: true, attachmentType: "Commercial Invoice", purpose: "货值、币种、发票金额，用于和采购支出 OA 核对" },
        { code: "sea_bill_of_lading", label: "提单/运单", required: true, attachmentType: "Logistics Bill", purpose: "提单号、柜号、船期、承运信息" },
        { code: "sea_forwarder_bill", label: "货代账单/费用清单", required: true, attachmentType: "Logistics Bill", purpose: "海运费、港杂费、货代服务费、杂费" },
        { code: "sea_clearance_fee", label: "清关费用资料（如有）", required: false, attachmentType: "Other", purpose: "报关费、清关费、预检费等费用依据" },
        { code: "sea_tax_certificate", label: "完税凭证（最终核对）", required: false, attachmentType: "Tax Certificate", purpose: "正式税费结果，用于和系统预估金额对照" },
        { code: "sea_other", label: "其他补充资料", required: false, attachmentType: "Other", purpose: "仓储费、滞留罚款、异常说明等补充依据" },
      ],
      AIR: [
        { code: "air_approval_attachment", label: "国际物流 OA 附件", required: false, oaSource: true, attachmentType: "Other", purpose: "系统优先从钉钉读取；缺失或需复核时再补传" },
        { code: "air_waybill", label: "空运运单", required: true, attachmentType: "Logistics Bill", purpose: "主单/分单、航班、实际重量、计费重量" },
        { code: "air_packing_list", label: "装箱单", required: true, attachmentType: "Packing List", purpose: "物料、数量、重量、体积、箱规" },
        { code: "air_commercial_invoice", label: "商业发票", required: true, attachmentType: "Commercial Invoice", purpose: "货值、币种、发票金额，用于和采购支出 OA 核对" },
        { code: "air_customs_declaration", label: "报关资料", required: true, attachmentType: "Customs Declaration", purpose: "报关单号、海关编码、申报品名" },
        { code: "air_forwarder_bill", label: "货代账单/费用清单", required: true, attachmentType: "Logistics Bill", purpose: "空运费、燃油附加费、服务费、杂费" },
        { code: "air_clearance_fee", label: "清关费用资料（如有）", required: false, attachmentType: "Other", purpose: "清关费、预检费等费用依据" },
        { code: "air_tax_certificate", label: "完税凭证（最终核对）", required: false, attachmentType: "Tax Certificate", purpose: "正式税费结果，用于和系统预估金额对照" },
        { code: "air_other", label: "其他补充资料", required: false, attachmentType: "Other", purpose: "仓储费、异常说明等补充依据" },
      ],
      EXPRESS: [
        { code: "express_approval_attachment", label: "国际物流 OA 附件", required: false, oaSource: true, attachmentType: "Other", purpose: "系统优先从钉钉读取；缺失或需复核时再补传" },
        { code: "express_waybill", label: "快递面单/运单", required: true, attachmentType: "Logistics Bill", purpose: "运单号、重量、收发件信息" },
        { code: "express_goods_list", label: "货品明细/装箱资料", required: true, attachmentType: "Packing List", purpose: "物料、数量、重量、体积" },
        { code: "express_commercial_invoice", label: "商业发票", required: true, attachmentType: "Commercial Invoice", purpose: "货值、币种、发票金额，用于和采购支出 OA 核对" },
        { code: "express_bill", label: "快递账单/费用清单", required: true, attachmentType: "Logistics Bill", purpose: "快递费、双清费用、服务费" },
        { code: "express_clearance_fee", label: "清关费用资料（如有）", required: false, attachmentType: "Other", purpose: "快递或双清产生清关费用时提供" },
        { code: "express_tax_certificate", label: "完税凭证（如有）", required: false, attachmentType: "Tax Certificate", purpose: "有正规进口清关时用于最终税费核对" },
        { code: "express_payment_voucher", label: "付款/对账凭证", required: false, attachmentType: "Other", purpose: "已付款金额、付款对象、对账依据" },
        { code: "express_other", label: "其他补充资料", required: false, attachmentType: "Other", purpose: "异常说明、补充截图、沟通记录等" },
      ],
    };
    return plans[logisticsType] || plans.SEA;
  }

  renderManualDocumentPanel(batch, logisticsType = "SEA", items = [], focus = {}) {
    const batchLabel = batch.batch_no || batch.waybill_no || batch.name;
    const tabs = this.manualDocumentLogisticsTabs()
      .map(
        (tab) => `
          <button class="ocw-manual-doc-tab ${tab.value === logisticsType ? "active" : ""}" type="button" data-action="manual-doc-logistics" data-logistics-type="${this.escape(tab.value)}">
            ${this.escape(tab.label)}
          </button>
        `
      )
      .join("");
    const plan = this.manualDocumentPlans(logisticsType);
    const bySlot = this.latestManualAttachmentBySlot(items);
    const requiredTotal = plan.filter((slot) => slot.required).length;
    const uploadedRequired = plan.filter((slot) => slot.required && bySlot[slot.code]).length;
    const uploadedTotal = plan.filter((slot) => bySlot[slot.code]).length;
    const missingRequired = Math.max(requiredTotal - uploadedRequired, 0);
    const focusSlotCodes = [...new Set(Array.isArray(focus.slotCodes) ? focus.slotCodes : focus.slotCode ? [focus.slotCode] : [])].filter(
      (slotCode) => slotCode && !bySlot[slotCode]
    );
    const focusedSlots = plan.filter((slot) => focusSlotCodes.includes(slot.code));
    const focusedLabels = focusedSlots.map((slot) => slot.label).join("、");
    return `
      <div class="ocw-manual-documents" data-logistics-type="${this.escape(logisticsType)}">
        <div class="ocw-purchase-target ocw-manual-document-target">
          <span>当前批次</span>
          <strong>${this.escape(batchLabel)}</strong>
          <em>这里用于补传缺失资料或给财务复核原件；钉钉已能拉到的不用重复上传。</em>
        </div>
        <div class="ocw-manual-doc-source-note">
          <span>基础信息来自国际物流 OA</span>
          <span>单价/币种来自采购支出 OA</span>
          <span>税费以报关/完税资料最终核对</span>
        </div>
        <div class="ocw-manual-doc-tabs">${tabs}</div>
        <div class="ocw-manual-doc-summary">
          <span>已补传 ${this.escape(String(uploadedTotal))} / ${this.escape(String(plan.length))}</span>
          <span>核算资料 ${this.escape(String(uploadedRequired))} / ${this.escape(String(requiredTotal))}</span>
          <span class="${missingRequired ? "warning" : "done"}">${missingRequired ? `${this.escape(String(missingRequired))} 项核算资料待确认` : "核算资料已补齐"}</span>
        </div>
        ${
          focusedSlots.length
            ? `
              <div class="ocw-manual-gap-fill-hint">
                <strong>已定位 ${this.escape(String(focusedSlots.length))} 处：${this.escape(focusedLabels)}</strong>
                <span>${this.escape(focus.label || focus.fieldname || "当前缺失项")}。上传资料或人工补填保存后，对应高亮会消失。</span>
              </div>
            `
            : ""
        }
        <div class="ocw-manual-doc-grid">
          ${this.renderManualDocumentCards(plan, bySlot, logisticsType, batch, { ...focus, slotCodes: focusSlotCodes })}
        </div>
      </div>
    `;
  }

  renderManualDocumentCards(plan = [], bySlot = {}, logisticsType = "SEA", batch = {}, focus = {}) {
    return plan
      .map((slot) => {
        const attachment = bySlot[slot.code] || null;
        const status = this.manualDocumentStatusInfo(slot, attachment, batch);
        const badge = this.manualDocumentBadgeInfo(slot);
        const fileName = attachment ? attachment.file_name || attachment.file_url || "--" : "";
        const focusSlotCodes = Array.isArray(focus.slotCodes) ? focus.slotCodes : focus.slotCode ? [focus.slotCode] : [];
        const focused = focusSlotCodes.includes(slot.code);
        return `
          <div class="ocw-manual-doc-card ${this.escape(status.className)} ${attachment ? "uploaded" : ""} ${focused ? "is-gap-focus" : ""}" data-slot-code="${this.escape(slot.code)}">
            <div class="ocw-manual-doc-card-head">
              <strong>${this.escape(slot.label)}</strong>
              <span class="ocw-manual-doc-required ${this.escape(badge.className)}">${this.escape(badge.label)}</span>
            </div>
            <div class="ocw-manual-doc-purpose">用于：${this.escape(slot.purpose)}</div>
            <div class="ocw-manual-doc-status">
              <span class="ocw-manual-doc-status-badge ${this.escape(status.className)}">${this.escape(status.label)}</span>
              ${attachment ? `<em title="${this.escape(fileName)}">${this.escape(fileName)}</em>` : `<em>${this.escape(status.note || (slot.oaSource ? "优先从钉钉读取" : "缺了再补传"))}</em>`}
            </div>
            <div class="ocw-manual-doc-actions">
              <button class="ocw-outline-btn ocw-mini-btn" type="button" data-action="upload-manual-document" data-logistics-type="${this.escape(logisticsType)}" data-slot-code="${this.escape(slot.code)}" data-slot-label="${this.escape(slot.label)}" data-attachment-type="${this.escape(slot.attachmentType)}" data-required="${slot.required ? "1" : "0"}">
                ${attachment ? "重传" : "上传"}
              </button>
              <button class="ocw-outline-btn ocw-mini-btn" type="button" data-action="manual-fill-gap" data-logistics-type="${this.escape(logisticsType)}" data-slot-code="${this.escape(slot.code)}" data-slot-label="${this.escape(slot.label)}" data-attachment-type="${this.escape(slot.attachmentType)}" data-required="${slot.required ? "1" : "0"}" data-gap-fieldname="${this.escape(focus.fieldname || "")}" data-gap-label="${this.escape(focus.label || slot.label)}">人工补填</button>
              ${
                attachment && attachment.file_url
                  ? `
                    <button class="ocw-outline-btn ocw-mini-btn" type="button" data-action="preview-manual-document" data-file-url="${this.escape(attachment.file_url)}" data-file-name="${this.escape(fileName)}">预览</button>
                    <button class="ocw-outline-btn ocw-mini-btn" type="button" data-action="download-manual-document" data-file-url="${this.escape(attachment.file_url)}" data-file-name="${this.escape(fileName)}">下载</button>
                  `
                  : ""
              }
              ${
                attachment
                  ? `<button class="ocw-outline-btn ocw-mini-btn danger" type="button" data-action="delete-manual-document" data-attachment-name="${this.escape(attachment.name)}" data-logistics-type="${this.escape(logisticsType)}">删除</button>`
                  : ""
              }
            </div>
          </div>
        `;
      })
      .join("");
  }

  latestManualAttachmentBySlot(items = []) {
    return items.reduce((map, item) => {
      const slotCode = item.slot_code || "";
      if (!slotCode) return map;
      map[slotCode] = item;
      return map;
    }, {});
  }

  manualDocumentStatusInfo(slot, attachment, batch = {}) {
    if (attachment) return { label: "已补传", className: "uploaded" };
    const sourceAttachmentCount = Number(batch.source_attachment_count || 0);
    if (slot.oaSource && sourceAttachmentCount > 0) {
      return { label: "已拉取", className: "uploaded", note: `已从钉钉拉取 ${sourceAttachmentCount} 个附件` };
    }
    if (slot.oaSource) return { label: "OA拉取", className: "oa" };
    if (slot.required) return { label: "待确认", className: "missing" };
    return { label: "可选补充", className: "optional" };
  }

  manualDocumentBadgeInfo(slot) {
    if (slot.oaSource) return { label: "OA拉取", className: "oa" };
    if (slot.required) return { label: "核算资料", className: "core" };
    return { label: "可选资料", className: "optional" };
  }

  async loadManualDocumentAttachments(batch, dialog, logisticsType = "SEA", focus = {}) {
    const result = await this.call(
      "overseas_costing.api.import_api.list_manual_document_attachments",
      {
        batch_name: batch.name,
        logistics_type: logisticsType,
        limit: 200,
      },
      true
    );
    const $target = dialog.$wrapper.find("[data-area='manual-documents']");
    if (!result || !result.ok) {
      $target.html(`
        <div class="ocw-purchase-empty">
          <strong>资料记录读取失败</strong>
          <span>${this.escape((result && result.message) || "请稍后重试。")}</span>
        </div>
      `);
      return;
    }
    $target.html(this.renderManualDocumentPanel(batch, logisticsType, result.items || [], focus));
    const focusSlotCodes = Array.isArray(focus.slotCodes) ? focus.slotCodes : focus.slotCode ? [focus.slotCode] : [];
    if (focusSlotCodes.length) {
      const target = $target
        .find("[data-slot-code]")
        .filter((index, element) => focusSlotCodes.includes($(element).attr("data-slot-code")))
        .get(0);
      if (target && typeof target.scrollIntoView === "function") {
        window.setTimeout(() => target.scrollIntoView({ behavior: "smooth", block: "center" }), 80);
      }
    }
  }

  openManualDocumentUploader(batch, dialog, logisticsType, slot) {
    if (!slot || !slot.code) {
      this.showPendingFeature("缺少资料类型，无法上传。");
      return;
    }
    if (!frappe.ui.FileUploader) {
      this.showPendingFeature("当前页面暂时无法打开文件上传器，请刷新后重试。");
      return;
    }
    new frappe.ui.FileUploader({
      allow_multiple: false,
      on_success: (fileDoc) => {
        const uploaded = Array.isArray(fileDoc) ? fileDoc[0] : fileDoc;
        this.registerManualDocumentAttachment(batch, dialog, logisticsType, slot, uploaded).catch((error) => this.showError(error));
      },
    });
    [0, 80, 200, 500, 1000, 2000].forEach((delay) => {
      window.setTimeout(() => this.localizeFrappeFileUploader(slot.label), delay);
    });
  }

  localizeFrappeFileUploader(slotLabel = "") {
    const $modal = $(".modal:visible")
      .filter((index, element) => {
        const $element = $(element);
        const title = $element.find(".modal-title").first().text().trim();
        return title === "Upload" || title === "上传资料" || $element.find(".file-uploader, .file-upload-area").length > 0;
      })
      .last();
    if (!$modal.length) return;

    $modal.addClass("ocw-file-uploader-zh");
    this.observeFrappeFileUploader($modal, slotLabel);
    const title = slotLabel ? `上传资料：${slotLabel}` : "上传资料";
    $modal.find(".modal-title").first().text(title);

    const replacements = {
      "Upload": "上传",
      "Set all private": "全部设为私有",
      "Drag and drop files here or upload from": "将文件拖到这里，或点击本地文件上传",
      "My Device": "本地文件",
      "Library": "文件库",
      "Link": "链接",
      "Camera": "摄像头",
      "Cancel": "取消",
      "Done": "完成",
      "Uploading": "上传中",
      "Upload Complete": "上传完成",
      "This file is public and can be accessed by anyone, even without logging in. Mark it private to limit access.":
        "文件已上传。",
    };
    $modal
      .find("*")
      .addBack()
      .contents()
      .filter(function () {
        return this.nodeType === 3 && String(this.nodeValue || "").trim();
      })
      .each(function () {
        const original = String(this.nodeValue || "");
        const trimmed = original.trim();
        const translated = replacements[trimmed];
        if (!translated) return;
        this.nodeValue = original.replace(trimmed, translated);
      });
    this.simplifyFrappeFileUploader($modal);
  }

  observeFrappeFileUploader($modal, slotLabel = "") {
    if (!$modal || !$modal.length || $modal.data("ocwUploaderObserver")) return;
    if (!window.MutationObserver) return;
    let timer = null;
    const observer = new MutationObserver(() => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => this.localizeFrappeFileUploader(slotLabel), 60);
    });
    observer.observe($modal.get(0), { childList: true, subtree: true, characterData: true });
    $modal.data("ocwUploaderObserver", observer);
    $modal.on("hidden.bs.modal.ocwUploaderObserver", () => {
      observer.disconnect();
      window.clearTimeout(timer);
      $modal.removeData("ocwUploaderObserver");
    });
  }

  simplifyFrappeFileUploader($modal) {
    if (!$modal || !$modal.length) return;
    const labelsToHide = ["文件库", "链接", "摄像头", "全部设为私有", "Private", "私有", "Public", "公开"];
    $modal
      .find("*")
      .addBack()
      .contents()
      .filter(function () {
        const text = String(this.nodeValue || "").trim();
        return this.nodeType === 3 && labelsToHide.includes(text);
      })
      .each(function () {
        const label = String(this.nodeValue || "").trim();
        const $textParent = $(this.parentNode);
        let $target = $textParent.closest("button, a, [role='button']");
        if (!$target.length) {
          let $candidate = $textParent;
          for (let i = 0; i < 5 && $candidate.length && !$candidate.hasClass("modal"); i += 1) {
            const compactText = $candidate.text().replace(/\s+/g, "");
            if (compactText === label) {
              $target = $candidate;
            }
            $candidate = $candidate.parent();
          }
        }
        if (!$target.length) {
          $target = $textParent;
        }
        $target.hide().attr("aria-hidden", "true");
      });
    this.hideFrappeFilePrivacyControls($modal);
  }

  hideFrappeFilePrivacyControls($modal) {
    const privacyTexts = ["Private", "私有", "Public", "公开"];
    $modal
      .find("*")
      .addBack()
      .contents()
      .filter(function () {
        const text = String(this.nodeValue || "").trim();
        return this.nodeType === 3 && privacyTexts.includes(text);
      })
      .each(function () {
        const $textParent = $(this.parentNode);
        const $target = $textParent.closest("label, .checkbox, .form-check, .control-input-wrapper, .file-privacy, .file-private");
        ($target.length ? $target : $textParent).hide().attr("aria-hidden", "true");
      });

    const warningPatterns = [
      "This file is public",
      "can be accessed by anyone",
      "Mark it private",
      "limit access",
      "文件是公开",
      "任何人都可以访问",
      "限制访问",
    ];
    $modal
      .find("*")
      .addBack()
      .contents()
      .filter(function () {
        const text = String(this.nodeValue || "").replace(/\s+/g, " ").trim();
        return this.nodeType === 3 && text && warningPatterns.some((pattern) => text.includes(pattern));
      })
      .each(function () {
        const $textParent = $(this.parentNode);
        const $target = $textParent.closest(".alert, .help-box, .file-public-warning, .file-upload-message, .text-warning, .bg-warning");
        ($target.length ? $target : $textParent).hide().attr("aria-hidden", "true");
      });
  }

  async registerManualDocumentAttachment(batch, dialog, logisticsType, slot, fileDoc = {}) {
    const fileUrl = fileDoc.file_url || fileDoc.file_url_private || "";
    if (!fileUrl) {
      this.showPendingFeature("文件上传成功但没有返回文件地址，请重新上传。");
      return;
    }
    const result = await this.call(
      "overseas_costing.api.import_api.register_manual_document_attachment",
      {
        batch_name: batch.name,
        version_name: batch.current_version || null,
        logistics_type: logisticsType,
        slot_code: slot.code,
        slot_label: slot.label,
        attachment_type: slot.attachmentType || "Other",
        file_url: fileUrl,
        file_name: fileDoc.file_name || fileDoc.name || "",
        required: slot.required ? 1 : 0,
      },
      true
    );
    if (!result || !result.ok) {
      this.showPendingFeature((result && result.message) || "资料登记失败。");
      return;
    }
    frappe.show_alert({ message: result.message || "资料已上传", indicator: "green" });
    await this.loadManualDocumentAttachments(batch, dialog, logisticsType, {
      slotCodes: Array.isArray(slot.focusSlotCodes) ? slot.focusSlotCodes : [],
    });
  }

  openManualGapFillDialog(batch, gap = {}, sourceDialog = null) {
    const logisticsType = gap.logisticsType || this.detectManualDocumentLogisticsType(batch);
    const slotCode = gap.slotCode || this.manualDocumentSlotForGap(batch, gap, logisticsType);
    const slot = this.manualDocumentPlans(logisticsType).find((item) => item.code === slotCode);
    if (!slot) {
      this.showPendingFeature("没有找到对应的资料位置，请先选择物流方式。");
      return;
    }
    const dialog = new frappe.ui.Dialog({
      title: `人工补填：${slot.label}`,
      fields: [
        {
          fieldtype: "HTML",
          fieldname: "manual_gap_context",
          options: `<div class="ocw-manual-gap-modal"><strong>${this.escape(slot.label)}</strong><span>${this.escape(gap.label || gap.fieldname || "当前缺失项")}</span><small>这里记录人工确认内容，不会把说明文字直接当作费用或系统字段值。</small></div>`,
        },
        {
          fieldtype: "Small Text",
          fieldname: "manual_note",
          label: "补填内容",
          reqd: 1,
          description: "例如：业务主体为 Empresas；或填写费用来源、金额、币种、确认人等。",
        },
        {
          fieldtype: "Small Text",
          fieldname: "remark",
          label: "备注",
        },
      ],
      primary_action_label: "保存补填",
      primary_action: () => {
        const values = dialog.get_values() || {};
        this.saveManualGapFillRecord(batch, dialog, sourceDialog, {
          ...gap,
          slotCode,
          slotLabel: slot.label,
          attachmentType: slot.attachmentType,
          required: slot.required,
          logisticsType,
          manualNote: values.manual_note,
          remark: values.remark,
        }).catch((error) => this.showError(error));
      },
    });
    dialog.show();
    dialog.$wrapper.addClass("ocw-manual-gap-modal");
  }

  async saveManualGapFillRecord(batch, dialog, sourceDialog, gap = {}) {
    const manualNote = String(gap.manualNote || "").trim();
    if (!manualNote) {
      this.showPendingFeature("请填写补填内容后再保存。");
      return;
    }
    const result = await this.call(
      "overseas_costing.api.import_api.register_manual_document_attachment",
      {
        batch_name: batch.name,
        version_name: batch.current_version || null,
        logistics_type: gap.logisticsType,
        slot_code: gap.slotCode,
        slot_label: gap.slotLabel,
        attachment_type: gap.attachmentType || "Other",
        file_url: "",
        file_name: gap.slotLabel,
        manual_note: manualNote,
        remark: String(gap.remark || "").trim(),
        required: gap.required ? 1 : 0,
      },
      true
    );
    if (!result || !result.ok) {
      this.showPendingFeature((result && result.message) || "人工补填保存失败。");
      return;
    }
    dialog.hide();
    frappe.show_alert({ message: result.message || "人工补填已保存", indicator: "green" });
    if (sourceDialog && sourceDialog.$wrapper) {
      await this.loadManualDocumentAttachments(batch, sourceDialog, gap.logisticsType, {
        fieldname: gap.fieldname,
        label: gap.label,
        slotCodes: gap.slotCodes || [gap.slotCode],
      });
    }
  }

  async deleteManualDocumentAttachment(batch, dialog, attachmentName = "", logisticsType = "SEA", focus = {}) {
    if (!attachmentName) {
      this.showPendingFeature("缺少资料记录，无法删除。");
      return;
    }
    const confirmed = await new Promise((resolve) => {
      frappe.confirm(
        "确认删除这条资料记录吗？删除后资料清单会重新显示为待补传。",
        () => resolve(true),
        () => resolve(false)
      );
    });
    if (!confirmed) return;
    const result = await this.call(
      "overseas_costing.api.import_api.delete_manual_document_attachment",
      { attachment_name: attachmentName },
      true
    );
    if (!result || !result.ok) {
      this.showPendingFeature((result && result.message) || "资料删除失败。");
      return;
    }
    frappe.show_alert({ message: result.message || "资料记录已删除", indicator: "green" });
    await this.loadManualDocumentAttachments(batch, dialog, logisticsType, focus);
    await this.refreshBatch(batch.name);
  }

  async parseManualDocumentAttachments(batch, dialog, $button = null) {
    if (!batch || this.isParsingManualDocuments) return;
    const logisticsType =
      dialog.$wrapper.find(".ocw-manual-documents").first().attr("data-logistics-type") ||
      this.detectManualDocumentLogisticsType(batch);
    this.isParsingManualDocuments = true;
    if ($button && $button.length) {
      $button.prop("disabled", true).text("解析中");
    }
    try {
      const result = await this.call(
        "overseas_costing.api.import_api.parse_manual_document_attachments",
        {
          batch_name: batch.name,
          logistics_type: logisticsType,
          limit: 80,
          skip_parsed: 1,
          recalculate: 1,
        },
        true
      );
      if (!result || !result.ok) {
        this.showOaAttachmentParseResult(result || { ok: false, message: "当前批次补传资料解析失败。" });
      } else {
        frappe.show_alert({ message: result.message || "当前补传资料已解析", indicator: "green" });
      }
      await this.loadManualDocumentAttachments(batch, dialog, logisticsType);
      await this.refreshBatch(batch.name);
    } finally {
      this.isParsingManualDocuments = false;
      if ($button && $button.length) {
        $button.prop("disabled", false).text("批量解析");
      }
    }
  }

  openLogisticsQuoteDialog(batchName = "") {
    const batch = batchName ? this.findBatch(batchName) : this.getActiveBatch();
    if (!batch) {
      this.showPendingFeature("当前没有可查看物流报价的批次。");
      return;
    }
    this.activeBatchName = batch.name;
    const sourceStatus = batch.source_status || {};
    const candidates = Array.isArray(sourceStatus.logistics_quote_candidates) ? sourceStatus.logistics_quote_candidates : [];
    const confirmed = sourceStatus.confirmed_logistics_quote || {};
    const logisticsTextSummary = sourceStatus.logistics_text_summary || {};
    const batchLabel = batch.waybill_no || batch.batch_no || batch.name;
    const candidateRows = candidates.length
      ? candidates
          .map((candidate, index) => {
            const isConfirmed = Number(confirmed.candidate_index) === index && this.isPositive(confirmed.amount);
            const carrier = candidate.carrier || "未标注供应商";
            const amount = `${this.formatNumber(candidate.amount)} ${candidate.currency || "RMB"}`;
            const volume = this.isPositive(candidate.volume_m3) ? ` · ${this.formatNumber(candidate.volume_m3)} 方` : "";
            return `
              <div class="ocw-purchase-source-row">
                <div>
                  <strong>${this.escape(carrier)}</strong>
                  <span>${this.escape(amount)}${this.escape(volume)}</span>
                  <em>${this.escape(candidate.evidence_line || "来源于 OA 物流报价字段")}</em>
                </div>
                ${
                  isConfirmed
                    ? '<span class="ocw-purchase-source-disabled">已确认</span>'
                    : `<button class="ocw-primary-btn ocw-mini-btn" data-action="confirm-logistics-quote" data-candidate-index="${index}">确认使用</button>`
                }
              </div>
            `;
          })
          .join("")
      : '<div class="ocw-purchase-empty-line">当前 OA 未识别到可确认的物流报价。请先确认审批单已填写“物流报价”文字或有明确物流费用字段。</div>';
    const confirmedHtml = this.isPositive(confirmed.amount)
      ? `<div class="ocw-purchase-apply"><div><strong>当前已确认</strong><span>${this.escape(confirmed.carrier || "未标注承运商/货代")} ${this.escape(`${this.formatNumber(confirmed.amount)} ${confirmed.currency || "RMB"}`)}，按${this.escape(this.allocationBasisLabel(confirmed.allocation_basis || "gross_weight"))}参与试算。</span></div></div>`
      : '<div class="ocw-purchase-note">候选报价仅用于辅助确认；未确认前不会写入费用分摊或综合成本。</div>';
    const manualDefaults = {
      carrier: confirmed.carrier || logisticsTextSummary.logistics_quote_carrier || "",
      amount: confirmed.amount || logisticsTextSummary.logistics_quote_amount || "",
      currency: confirmed.currency || logisticsTextSummary.logistics_quote_currency || "RMB",
      allocation_basis: confirmed.allocation_basis || "gross_weight",
      gross_weight_kg: confirmed.gross_weight_kg || logisticsTextSummary.gross_weight_kg || "",
      chargeable_weight_kg: confirmed.chargeable_weight_kg || "",
      unit_freight_per_kg: confirmed.unit_freight_per_kg || "",
      billing_method: confirmed.billing_method || "",
      pre_delivery_date: confirmed.pre_delivery_date || logisticsTextSummary.pre_delivery_date || "",
      destination: confirmed.destination || logisticsTextSummary.destination || "",
      evidence_text: confirmed.evidence_line || logisticsTextSummary.logistics_quote_evidence || "",
      note: confirmed.confirmation_note || "",
    };
    const dialog = new frappe.ui.Dialog({
      title: "物流报价/运费补录",
      fields: [
        {
          fieldtype: "HTML",
          fieldname: "logistics_quote",
          options: `
            <div class="ocw-purchase-preview">
              <div class="ocw-purchase-target">
                <span>当前批次</span>
                <strong>${this.escape(batchLabel)}</strong>
                <em>系统从国际物流 OA 的文字报价中提取候选；确认后会记录来源、操作人和时间。</em>
              </div>
              ${confirmedHtml}
              <div class="ocw-purchase-source-list">${candidateRows}</div>
              <div class="ocw-manual-quote-box">
                <div class="ocw-manual-quote-head">
                  <strong>手工补录物流报价</strong>
                  <span>用于 OA 文本能看到费用、但系统没有自动写入的情况；保存后会进入费用池并重新试算。</span>
                </div>
                <div class="ocw-manual-quote-grid">
                  <label>
                    <span>承运商/货代</span>
                    <input class="form-control" data-field="carrier" value="${this.escape(manualDefaults.carrier)}" placeholder="如 DHL、SISA、货代名称">
                  </label>
                  <label>
                    <span>物流费用金额</span>
                    <input class="form-control" data-field="amount" type="number" step="0.000001" value="${this.escape(manualDefaults.amount)}" placeholder="如 6160.615461">
                  </label>
                  <label>
                    <span>币种</span>
                    <select class="form-control" data-field="currency">
                      ${this.renderManualQuoteOption("RMB", "人民币 RMB", manualDefaults.currency)}
                      ${this.renderManualQuoteOption("USD", "美元 USD", manualDefaults.currency)}
                      ${this.renderManualQuoteOption("MXN", "比索 MXN", manualDefaults.currency)}
                    </select>
                  </label>
                  <label>
                    <span>分摊依据</span>
                    <select class="form-control" data-field="allocation_basis">
                      ${this.renderManualQuoteOption("gross_weight", "按毛重分摊", manualDefaults.allocation_basis)}
                      ${this.renderManualQuoteOption("chargeable_weight", "按计费重分摊", manualDefaults.allocation_basis)}
                      ${this.renderManualQuoteOption("volume", "按体积分摊", manualDefaults.allocation_basis)}
                      ${this.renderManualQuoteOption("goods_value", "按货值分摊", manualDefaults.allocation_basis)}
                    </select>
                  </label>
                  <label>
                    <span>实际重量 KG</span>
                    <input class="form-control" data-field="gross_weight_kg" type="number" step="0.000001" value="${this.escape(manualDefaults.gross_weight_kg)}">
                  </label>
                  <label>
                    <span>计费重量 KG</span>
                    <input class="form-control" data-field="chargeable_weight_kg" type="number" step="0.000001" value="${this.escape(manualDefaults.chargeable_weight_kg)}">
                  </label>
                  <label>
                    <span>每 KG 单价</span>
                    <input class="form-control" data-field="unit_freight_per_kg" type="number" step="0.000001" value="${this.escape(manualDefaults.unit_freight_per_kg)}">
                  </label>
                  <label>
                    <span>预计发货日期</span>
                    <input class="form-control" data-field="pre_delivery_date" value="${this.escape(manualDefaults.pre_delivery_date)}" placeholder="如 2026/7/15">
                  </label>
                  <label class="ocw-manual-quote-wide">
                    <span>目的地</span>
                    <input class="form-control" data-field="destination" value="${this.escape(manualDefaults.destination)}">
                  </label>
                  <label class="ocw-manual-quote-wide">
                    <span>计费说明/备注</span>
                    <input class="form-control" data-field="billing_method" value="${this.escape(manualDefaults.billing_method)}" placeholder="如体积重大于实际重量，按计费重">
                  </label>
                  <label class="ocw-manual-quote-full">
                    <span>来源依据</span>
                    <textarea class="form-control" data-field="evidence_text" rows="3" placeholder="可粘贴审批单里的报价公式或关键原文">${this.escape(manualDefaults.evidence_text)}</textarea>
                  </label>
                  <label class="ocw-manual-quote-full">
                    <span>人工备注</span>
                    <input class="form-control" data-field="note" value="${this.escape(manualDefaults.note)}" placeholder="可填写核对说明">
                  </label>
                </div>
                <div class="ocw-manual-quote-actions">
                  <button class="ocw-primary-btn" type="button" data-action="save-manual-logistics-quote">保存补录并重新试算</button>
                </div>
              </div>
            </div>
          `,
        },
      ],
      primary_action_label: "关闭",
      primary_action: () => dialog.hide(),
    });
    dialog.show();
    dialog.$wrapper.addClass("ocw-purchase-modal");
    dialog.$wrapper.off("click.ocwLogisticsQuote").on("click.ocwLogisticsQuote", "[data-action='confirm-logistics-quote']", (event) => {
      const index = Number($(event.currentTarget).attr("data-candidate-index"));
      this.confirmLogisticsQuoteCandidate(batch, candidates[index], index, dialog).catch((error) => this.showError(error));
    });
    dialog.$wrapper.on("click.ocwLogisticsQuote", "[data-action='save-manual-logistics-quote']", () => {
      this.saveManualLogisticsQuote(batch, dialog).catch((error) => this.showError(error));
    });
  }

  renderManualQuoteOption(value, label, selectedValue) {
    const normalizedSelected = String(selectedValue || "").trim();
    const selected = normalizedSelected === value ? " selected" : "";
    return `<option value="${this.escape(value)}"${selected}>${this.escape(label)}</option>`;
  }

  readManualQuoteValue(dialog, fieldname) {
    return String(dialog.$wrapper.find(`[data-field='${fieldname}']`).val() || "").trim();
  }

  async saveManualLogisticsQuote(batch, dialog) {
    if (!batch || this.isSavingManualLogisticsQuote) return;
    const payload = {
      batch_name: batch.name,
      version_name: batch.current_version || null,
      carrier: this.readManualQuoteValue(dialog, "carrier"),
      amount: this.readManualQuoteValue(dialog, "amount"),
      currency: this.readManualQuoteValue(dialog, "currency") || "RMB",
      allocation_basis: this.readManualQuoteValue(dialog, "allocation_basis") || "gross_weight",
      gross_weight_kg: this.readManualQuoteValue(dialog, "gross_weight_kg"),
      chargeable_weight_kg: this.readManualQuoteValue(dialog, "chargeable_weight_kg"),
      unit_freight_per_kg: this.readManualQuoteValue(dialog, "unit_freight_per_kg"),
      billing_method: this.readManualQuoteValue(dialog, "billing_method"),
      evidence_text: this.readManualQuoteValue(dialog, "evidence_text"),
      pre_delivery_date: this.readManualQuoteValue(dialog, "pre_delivery_date"),
      destination: this.readManualQuoteValue(dialog, "destination"),
      note: this.readManualQuoteValue(dialog, "note"),
    };
    if (!this.isPositive(payload.amount)) {
      frappe.msgprint("请先填写大于 0 的物流费用金额。");
      return;
    }
    const confirmed = await new Promise((resolve) => {
      frappe.confirm(
        `
          <div class="ocw-confirm-copy">
            <h4>确认保存物流报价补录？</h4>
            <p>系统会把 ${this.escape(this.formatNumber(payload.amount))} ${this.escape(payload.currency)} 写入当前批次费用池，并立即重新试算。</p>
            <div class="ocw-confirm-note">保存后仍可再次修改补录金额，修改记录会保留。</div>
          </div>
        `,
        () => resolve(true),
        () => resolve(false)
      );
    });
    if (!confirmed) return;

    this.isSavingManualLogisticsQuote = true;
    const $button = dialog.$wrapper.find("[data-action='save-manual-logistics-quote']");
    $button.prop("disabled", true).text("保存中...");
    try {
      const result = await this.call("overseas_costing.api.import_api.save_manual_logistics_quote", payload, true);
      if (!result || !result.ok) {
        throw new Error((result && result.message) || "物流报价补录保存失败");
      }
      dialog.hide();
      await this.loadBatches();
      const refreshed = this.findBatch(result.batch_name || batch.name) || batch;
      if (refreshed) {
        await this.loadBatchItems(refreshed.name, refreshed.current_version, true).catch((error) => this.showError(error));
        await this.loadAuditLogs(refreshed.name, refreshed.current_version).catch((error) => this.showError(error));
      }
      this.renderTable();
      this.renderDiffPanel();
      if (this.drawerBatchName === batch.name && this.$root.find("[data-area='batch-drawer']").hasClass("is-open")) {
        this.renderBatchDrawer();
      }
      frappe.show_alert({ message: result.message || "物流报价补录已保存", indicator: "green" });
    } finally {
      this.isSavingManualLogisticsQuote = false;
      $button.prop("disabled", false).text("保存补录并重新试算");
    }
  }

  async confirmLogisticsQuoteCandidate(batch, candidate, candidateIndex, dialog) {
    if (!batch || !candidate || this.isConfirmingLogisticsQuote) return;
    const carrier = candidate.carrier || "未标注供应商";
    const amount = `${this.formatNumber(candidate.amount)} ${candidate.currency || "RMB"}`;
    const confirmed = await new Promise((resolve) => {
      frappe.confirm(
        `
          <div class="ocw-confirm-copy">
            <h4>确认使用该物流报价？</h4>
            <p>将确认 ${this.escape(carrier)} 的 ${this.escape(amount)}，生成整票物流费用分摊规则并重新试算。</p>
            <div class="ocw-confirm-note">确认后仍可改选其他候选，系统会保留每次确认记录。</div>
          </div>
        `,
        () => resolve(true),
        () => resolve(false)
      );
    });
    if (!confirmed) return;

    this.isConfirmingLogisticsQuote = true;
    try {
      const result = await this.call(
        "overseas_costing.api.import_api.confirm_logistics_quote_candidate",
        {
          batch_name: batch.name,
          version_name: batch.current_version || null,
          candidate_index: candidateIndex,
        },
        true
      );
      if (!result || !result.ok) {
        throw new Error((result && result.message) || "物流报价确认失败");
      }
      dialog.hide();
      await this.loadBatches();
      frappe.show_alert({ message: result.message || "物流报价已确认", indicator: "green" });
    } finally {
      this.isConfirmingLogisticsQuote = false;
    }
  }

  openRowMoreDialog(batchName = "") {
    const batch = batchName ? this.findBatch(batchName) : this.getActiveBatch();
    if (!batch) {
      this.showPendingFeature("当前没有可操作的批次。");
      return;
    }
    this.activeBatchName = batch.name;
    const batchLabel = batch.batch_no || batch.waybill_no || batch.name;
    const dialog = new frappe.ui.Dialog({
      title: "更多操作",
      fields: [
        {
          fieldtype: "HTML",
          fieldname: "row_more",
          options: `
            <div class="ocw-quick-panel">
              <div class="ocw-quick-context">
                <span>当前批次</span>
                <strong>${this.escape(batchLabel)}</strong>
              </div>
              <button class="ocw-quick-card" data-action="more-open-dingtalk">
                <strong>审批单</strong>
                <span>打开钉钉原始审批表</span>
              </button>
              <button class="ocw-quick-card danger" data-action="more-delete">
                <strong>删除批次</strong>
                <span>删除前仍会二次确认</span>
              </button>
            </div>
          `,
        },
      ],
      primary_action_label: "关闭",
      primary_action: () => dialog.hide(),
    });
    dialog.show();
    dialog.$wrapper.addClass("ocw-quick-modal");
    dialog.$wrapper
      .off("click.ocwRowMore")
      .on("click.ocwRowMore", "[data-action='more-open-dingtalk']", () => {
        dialog.hide();
        this.openDingtalkOrder(batch.name);
      })
      .on("click.ocwRowMore", "[data-action='more-delete']", () => {
        dialog.hide();
        this.confirmDeleteBatch(batch.name);
      });
  }

  openOaAttachmentDialog(batchName = "") {
    const batch = batchName ? this.findBatch(batchName) : this.getActiveBatch();
    if (!batch) {
      this.showPendingFeature("当前没有可查看附件的批次。");
      return;
    }
    this.activeBatchName = batch.name;
    const batchLabel = batch.batch_no || batch.waybill_no || batch.name;
    const dialog = new frappe.ui.Dialog({
      title: "发起附件",
      size: "large",
      fields: [
        {
          fieldtype: "HTML",
          fieldname: "oa_attachments",
          options: `
            <div class="ocw-purchase-target">
              <span>当前批次</span>
              <strong>${this.escape(batchLabel)}</strong>
              <em>只显示钉钉审批发起表单上传的附件；评论附件暂不纳入。</em>
            </div>
            <div class="ocw-purchase-loading" data-area="oa-attachment-list">正在读取发起附件</div>
          `,
        },
      ],
      primary_action_label: "关闭",
      primary_action: () => dialog.hide(),
    });
    dialog.show();
    dialog.$wrapper.addClass("ocw-purchase-modal ocw-oa-attachment-modal");
    dialog.$wrapper
      .off("click.ocwOaAttachments")
      .on("click.ocwOaAttachments", "[data-action='open-generic-link']", (event) => {
        this.openDingtalkLink($(event.currentTarget).attr("data-open-url"));
      })
      .on("click.ocwOaAttachments", "[data-action='download-oa-attachment']", (event) => {
        this.downloadOaFormAttachment(
          batch,
          dialog,
          $(event.currentTarget).attr("data-attachment-name"),
          $(event.currentTarget),
          $(event.currentTarget).attr("data-open-parse-after-download") === "1"
        ).catch((error) => this.showError(error));
      })
      .on("click.ocwOaAttachments", "[data-action='preview-oa-attachment-file']", (event) => {
        this.openOaAttachmentFilePreview(
          batch,
          dialog,
          $(event.currentTarget).attr("data-attachment-name"),
          $(event.currentTarget).attr("data-file-url"),
          $(event.currentTarget).attr("data-file-name"),
          $(event.currentTarget)
        ).catch((error) => this.showError(error));
      });
    this.loadOaFormAttachments(batch, dialog).catch((error) => {
      dialog.$wrapper.find("[data-area='oa-attachment-list']").html(`
        <div class="ocw-purchase-empty">
          <strong>发起附件读取失败</strong>
          <span>${this.escape(this.normalizeErrorMessage(error))}</span>
        </div>
      `);
    });
  }

  async loadOaFormAttachments(batch, dialog) {
    const result = await this.call(
      "overseas_costing.api.import_api.list_oa_form_attachments",
      {
        batch_name: batch.name,
        limit: 80,
      },
      true
    );
    const $target = dialog.$wrapper.find("[data-area='oa-attachment-list']");
    if (!result || !result.ok) {
      $target.html(`
        <div class="ocw-purchase-empty">
          <strong>暂时无法读取发起附件</strong>
          <span>${this.escape((result && result.message) || "当前批次没有可读取的发起附件。")}</span>
        </div>
      `);
      return;
    }
    $target.removeClass("ocw-purchase-loading").html(this.renderOaAttachmentList(result.items || []));
  }

  async downloadOaFormAttachment(batch, dialog, attachmentName = "", $button = null, openParseAfterDownload = false) {
    if (!attachmentName) {
      this.showPendingFeature("缺少附件记录，无法下载。");
      return;
    }
    if ($button && $button.length) {
      $button.prop("disabled", true).text("下载中");
    }
    const result = await this.call(
      "overseas_costing.api.import_api.download_oa_form_attachment",
      {
        attachment_name: attachmentName,
      },
      true
    );
    if (!result || !result.ok) {
      if ($button && $button.length) {
        $button.prop("disabled", false).text(result && result.error_type ? "重试下载" : "下载到本地");
      }
      this.showPendingFeature((result && result.message) || "钉钉附件下载失败。");
      if (batch && dialog) {
        await this.loadOaFormAttachments(batch, dialog);
      }
      return;
    }
    if (result.file_url) {
      this.downloadFileToLocal(result.file_url, result.file_name || "");
    }
    frappe.show_alert({
      message: "附件已开始下载到本地",
      indicator: "green",
    });
    await this.loadOaFormAttachments(batch, dialog);
    if (openParseAfterDownload && result.file_url) {
      this.openPackingListPreviewDialog(batch.name, result.attachment_name || attachmentName, result.file_url);
    }
  }

  downloadFileToLocal(fileUrl, fileName = "") {
    if (!fileUrl) return;
    const link = document.createElement("a");
    link.href = fileUrl;
    if (fileName) link.download = fileName;
    link.target = "_self";
    link.style.display = "none";
    document.body.appendChild(link);
    link.click();
    window.setTimeout(() => link.remove(), 0);
  }

  async openOaAttachmentFilePreview(batch, parentDialog, attachmentName = "", fileUrl = "", fileName = "", $button = null) {
    let previewUrl = fileUrl || "";
    let previewName = fileName || "";
    if (!previewUrl && attachmentName) {
      if ($button && $button.length) {
        $button.prop("disabled", true).text("准备预览");
      }
      const result = await this.call(
        "overseas_costing.api.import_api.download_oa_form_attachment",
        {
          attachment_name: attachmentName,
        },
        true
      );
      if (!result || !result.ok) {
        if ($button && $button.length) {
          $button.prop("disabled", false).text(result && result.error_type ? "重试预览" : "附件预览");
        }
        this.showPendingFeature((result && result.message) || "钉钉附件下载失败，暂时无法预览。");
        if (batch && parentDialog) {
          await this.loadOaFormAttachments(batch, parentDialog);
        }
        return;
      }
      previewUrl = result.file_url || "";
      previewName = result.file_name || previewName;
      frappe.show_alert({
        message: "附件已保存，可预览",
        indicator: "green",
      });
      if (batch && parentDialog) {
        await this.loadOaFormAttachments(batch, parentDialog);
      }
    }
    if (!previewUrl) {
      this.showPendingFeature("当前附件还没有可预览的文件。");
      return;
    }
    this.openOaAttachmentFilePreviewDialog(previewUrl, previewName || attachmentName || "附件");
  }

  openOaAttachmentFilePreviewDialog(fileUrl = "", fileName = "") {
    const dialog = new frappe.ui.Dialog({
      title: "附件预览",
      size: "large",
      fields: [
        {
          fieldtype: "HTML",
          fieldname: "oa_attachment_file_preview",
          options: this.renderOaAttachmentFilePreview(fileUrl, fileName),
        },
      ],
      primary_action_label: "关闭",
      primary_action: () => dialog.hide(),
    });
    dialog.show();
    dialog.$wrapper.addClass("ocw-purchase-modal ocw-attachment-file-preview-modal");
  }

  renderOaAttachmentFilePreview(fileUrl = "", fileName = "") {
    const fileRef = fileName || fileUrl;
    const downloadLink = `
      <a class="ocw-link-btn" href="${this.escape(fileUrl)}" download="${this.escape(fileName || "")}" target="_self">下载到本地</a>
    `;
    let previewBody = "";
    if (this.isImageFileRef(fileRef)) {
      previewBody = `<img class="ocw-attachment-file-preview-image" src="${this.escape(fileUrl)}" alt="${this.escape(fileName || "附件预览")}">`;
    } else if (this.isPdfFileRef(fileRef) || this.isTextFileRef(fileRef)) {
      previewBody = `<iframe class="ocw-attachment-file-preview-frame" src="${this.escape(fileUrl)}" title="${this.escape(fileName || "附件预览")}"></iframe>`;
    } else {
      previewBody = `
        <div class="ocw-purchase-empty">
          <strong>当前格式暂不支持页面内预览</strong>
          <span>请下载到本地查看原文件，系统仍会保留附件记录用于回溯。</span>
        </div>
      `;
    }
    return `
      <div class="ocw-attachment-file-preview">
        <div class="ocw-purchase-target ocw-source-document-target">
          <span>原始附件</span>
          <strong>${this.escape(fileName || "--")}</strong>
          <em>这里显示的是钉钉发起附件原件，供人工复核使用，不代表系统已完整解析。</em>
        </div>
        <div class="ocw-attachment-file-preview-actions">${downloadLink}</div>
        <div class="ocw-attachment-file-preview-body">${previewBody}</div>
      </div>
    `;
  }

  openOaSourceAttachmentPreview(attachmentName = "", batch = null, parentDialog = null) {
    if (!attachmentName) {
      this.showPendingFeature("缺少附件记录，无法查看内容。");
      return;
    }
    const dialog = new frappe.ui.Dialog({
      title: "附件内容识别预览",
      size: "large",
      fields: [
        {
          fieldtype: "HTML",
          fieldname: "source_attachment_preview",
          options: '<div class="ocw-purchase-loading" data-area="source-attachment-preview">正在识别附件内容</div>',
        },
      ],
      primary_action_label: "关闭",
      primary_action: () => dialog.hide(),
    });
    dialog.show();
    dialog.$wrapper.addClass("ocw-purchase-modal ocw-source-attachment-modal");
    dialog.$wrapper
      .off("click.ocwSourceAttachmentReview")
      .on("click.ocwSourceAttachmentReview", "[data-action='confirm-source-attachment-type']", (event) => {
        this.confirmOaSourceAttachmentType(
          dialog,
          attachmentName,
          batch,
          parentDialog,
          $(event.currentTarget)
        ).catch((error) => this.showError(error));
      })
      .on("click.ocwSourceAttachmentReview", "[data-action='preview-purchase-order-match']", () => {
        this.openPurchaseOrderMatchDialog(attachmentName, batch, parentDialog, dialog);
    });
    this.call("overseas_costing.api.import_api.preview_oa_source_attachment", { attachment_name: attachmentName }, true)
      .then(async (result) => {
        this.renderOaSourceAttachmentPreview(dialog, result, batch, parentDialog);
        if (result && result.ok && batch && parentDialog) {
          await this.loadOaFormAttachments(batch, parentDialog);
        }
      })
      .catch((error) => this.renderOaSourceAttachmentPreview(dialog, { ok: false, message: this.normalizeErrorMessage(error) }, batch, parentDialog));
  }

  renderOaSourceAttachmentPreview(dialog, result, batch = null, parentDialog = null) {
    const $target = dialog.$wrapper.find("[data-area='source-attachment-preview']");
    if (!result || !result.ok) {
      $target.html(`
        <div class="ocw-purchase-empty">
          <strong>附件内容暂时无法识别</strong>
          <span>${this.escape((result && result.message) || "请先确认附件已下载到系统。")}</span>
        </div>
      `);
      return;
    }
    const classification = result.classification || {};
    const fields = result.field_candidates || {};
    const manualReview = result.manual_review || {};
    const purchaseOrder = result.purchase_order || {};
    const isPurchaseOrder = classification.code === "purchase_order" || manualReview.confirmed_type === "purchase_order";
    const selectedType = manualReview.confirmed_type || this.sourceAttachmentTypeFromClassification(classification.code);
    const typeOptions = [
      ["purchase_order", "采购订单"],
      ["purchase_price_document", "采购价格资料"],
      ["customs_declaration", "报关资料"],
      ["tax_certificate", "完税凭证"],
      ["logistics_quote", "物流报价"],
      ["other", "其他资料"],
    ]
      .map(([value, label]) => `<option value="${value}" ${value === selectedType ? "selected" : ""}>${label}</option>`)
      .join("");
    const candidateRows = [
      ["物料编码候选", (fields.material_codes || []).join("、") || "--"],
      ["海关编码候选", (fields.hs_codes || []).join("、") || "--"],
      ["币种候选", (fields.currencies || []).join("、") || "--"],
      ["单价候选", this.isPositive(fields.unit_price_candidate) ? this.formatNumber(fields.unit_price_candidate) : "--"],
      ["金额候选", this.isPositive(fields.goods_value_candidate) ? this.formatNumber(fields.goods_value_candidate) : "--"],
      ["报关单号候选", fields.pedimento_no_candidate || "--"],
      ["实缴税费候选 MXN", this.isPositive(fields.paid_total_mxn_candidate) ? this.formatNumber(fields.paid_total_mxn_candidate) : "--"],
      ["税费合计候选 MXN", this.isPositive(fields.tax_total_mxn_candidate) ? this.formatNumber(fields.tax_total_mxn_candidate) : "--"],
    ]
      .map(([label, value]) => `<tr><th>${this.escape(label)}</th><td>${this.escape(String(value))}</td></tr>`)
      .join("");
    const methodLabels = {
      pdf_layout_text: "PDF 版面文本",
      pdf_text: "PDF 文字层",
      ocr_pdf: "扫描 PDF OCR",
      ocr_image: "图片 OCR",
      word_docx: "Word 文本",
      word_doc: "Word 文本",
      txt_text: "TXT 文本",
    };
    const methodLabel = methodLabels[result.extraction_method] || "文档文本";
    $target.html(`
      <div class="ocw-purchase-target ocw-source-document-target">
        <span>附件</span>
        <strong>${this.escape(result.source_name || "--")}</strong>
        <em>${this.escape(methodLabel)}；识别结果仅用于资料分类和人工核对，当前不会写入单价、货值。</em>
      </div>
      <div class="ocw-purchase-apply ocw-source-document-classification">
        <div>
          <strong>${this.escape(classification.label || "待人工识别")}</strong>
          <span>${this.escape(classification.reason || "")}</span>
        </div>
      </div>
      ${isPurchaseOrder ? `
        <section class="ocw-purchase-section ocw-purchase-order-entry ocw-source-purchase-order-entry">
          <div class="ocw-purchase-order-summary">
            <span>订单号</span><strong>${this.escape(purchaseOrder.purchase_order_no || "--")}</strong>
            <span>供应商</span><strong>${this.escape(purchaseOrder.supplier || "--")}</strong>
            <span>币种</span><strong>${this.escape(purchaseOrder.currency || "--")}</strong>
          </div>
          <button class="btn btn-primary btn-sm" type="button" data-action="preview-purchase-order-match">查看物料匹配</button>
        </section>
      ` : ""}
      <section class="ocw-purchase-section ocw-source-document-review">
        <h4>人工确认</h4>
        <div class="ocw-source-document-review-controls">
          <select class="form-control" data-field="source-attachment-type">${typeOptions}</select>
          <input class="form-control" data-field="source-attachment-remark" type="text" maxlength="240" placeholder="备注（可选）" value="${this.escape(manualReview.remark || "")}">
          <button class="btn btn-primary btn-sm" type="button" data-action="confirm-source-attachment-type">确认资料类型</button>
        </div>
        ${manualReview.status === "confirmed" ? `<div class="ocw-confirm-note">已确认：${this.escape(manualReview.confirmed_type_label || "--")}${manualReview.confirmed_by ? `，${this.escape(manualReview.confirmed_by)}` : ""}${manualReview.confirmed_at ? `，${this.escape(manualReview.confirmed_at)}` : ""}</div>` : ""}
      </section>
      <section class="ocw-purchase-section">
        <h4>字段候选</h4>
        <div class="ocw-purchase-table-wrap ocw-field-candidate-wrap">
          <table class="ocw-purchase-table ocw-field-candidate-table"><tbody>${candidateRows}</tbody></table>
        </div>
      </section>
      <section class="ocw-purchase-section">
        <h4>识别文本</h4>
        <pre class="ocw-attachment-ocr-text">${this.escape(result.text_excerpt || "未识别到可用文字")}</pre>
      </section>
    `);
  }

  sourceAttachmentTypeFromClassification(code = "") {
    const supported = ["purchase_order", "purchase_price_document", "customs_declaration", "tax_certificate", "logistics_quote"];
    return supported.includes(code) ? code : "other";
  }

  async confirmOaSourceAttachmentType(dialog, attachmentName = "", batch = null, parentDialog = null, $button = null) {
    if (!attachmentName) {
      this.showPendingFeature("缺少附件记录，无法保存确认结果。");
      return;
    }
    const confirmedType = dialog.$wrapper.find("[data-field='source-attachment-type']").val();
    const remark = dialog.$wrapper.find("[data-field='source-attachment-remark']").val();
    if ($button && $button.length) {
      $button.prop("disabled", true).text("保存中");
    }
    try {
      const result = await this.call(
        "overseas_costing.api.import_api.confirm_oa_source_attachment_type",
        {
          attachment_name: attachmentName,
          confirmed_type: confirmedType,
          remark: remark || "",
        },
        true
      );
      if (!result || !result.ok) {
        this.showPendingFeature((result && result.message) || "附件类型确认失败。");
        return;
      }
      frappe.show_alert({ message: result.message || "附件资料类型已确认", indicator: "green" });
      if (batch && parentDialog) {
        await this.loadOaFormAttachments(batch, parentDialog);
        await this.refreshBatch(batch.name);
      }
      dialog.hide();
    } finally {
      if ($button && $button.length && dialog.$wrapper.is(":visible")) {
        $button.prop("disabled", false).text("确认资料类型");
      }
    }
  }

  openPurchaseOrderMatchDialog(attachmentName = "", batch = null, attachmentListDialog = null, sourcePreviewDialog = null) {
    if (!attachmentName) {
      this.showPendingFeature("缺少采购订单附件，无法生成物料匹配预览。");
      return;
    }
    const dialog = new frappe.ui.Dialog({
      title: "采购订单匹配预览",
      size: "large",
      fields: [
        {
          fieldtype: "HTML",
          fieldname: "purchase_order_match_preview",
          options: '<div class="ocw-purchase-loading" data-area="purchase-order-match-preview">正在生成采购订单匹配预览</div>',
        },
      ],
      primary_action_label: "关闭",
      primary_action: () => dialog.hide(),
    });
    dialog.show();
    dialog.$wrapper.addClass("ocw-purchase-modal");
    dialog.$wrapper
      .off("click.ocwPurchaseOrderMatch")
      .on("click.ocwPurchaseOrderMatch", "[data-action='apply-purchase-order-match']", (event) => {
        this.applyPurchaseOrderMatch(
          dialog,
          attachmentName,
          batch,
          attachmentListDialog,
          sourcePreviewDialog,
          $(event.currentTarget)
        ).catch((error) => this.showError(error));
      });
    this.call(
      "overseas_costing.api.import_api.preview_oa_purchase_order_match",
      { attachment_name: attachmentName },
      true
    )
      .then((result) => this.renderPurchaseOrderMatchPreview(dialog, result))
      .catch((error) => this.renderPurchaseOrderMatchPreview(dialog, { ok: false, message: this.normalizeErrorMessage(error) }));
  }

  renderPurchaseOrderMatchPreview(dialog, result) {
    const $target = dialog.$wrapper.find("[data-area='purchase-order-match-preview']");
    if (!result || !result.ok) {
      $target.html(`
        <div class="ocw-purchase-empty">
          <strong>暂时无法生成采购订单匹配</strong>
          <span>${this.escape((result && result.message) || "请确认附件已下载且识别出完整价格明细。")}</span>
        </div>
      `);
      return;
    }
    const purchaseOrder = result.purchase_order || {};
    const writeback = result.writeback_preview || {};
    const rows = this.renderPurchaseOrderMatchRows(result.source_rows || [], writeback);
    const hasFillable = Number(writeback.fillable_row_count || 0) > 0;
    $target.html(`
      <div class="ocw-purchase-target">
        <span>采购订单</span>
        <strong>${this.escape(purchaseOrder.purchase_order_no || "--")}</strong>
        <em>${this.escape(purchaseOrder.supplier || "--")} / ${this.escape(purchaseOrder.currency || "--")}</em>
      </div>
      <div class="ocw-purchase-order-stats">
        <span>识别 ${this.escape(String(purchaseOrder.recognized_line_count || 0))} 条</span>
        <span>匹配 ${this.escape(String(writeback.matched_count || 0))} 条</span>
        <span>可补 ${this.escape(String(writeback.fillable_row_count || 0))} 条</span>
        <span>冲突 ${this.escape(String(writeback.conflict_row_count || 0))} 条</span>
        <span>未匹配 ${this.escape(String(writeback.unmatched_count || 0))} 条</span>
      </div>
      <section class="ocw-purchase-section">
        <div class="ocw-purchase-table-wrap">
          <table class="ocw-purchase-table ocw-purchase-order-table">
            <thead><tr><th>物料编码</th><th>物料名称</th><th>数量</th><th>采购单价</th><th>币种</th><th>采购货值</th><th>匹配结果</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </section>
      <div class="ocw-purchase-order-footer">
        <span>${this.escape(writeback.message || result.message || "")}</span>
        ${hasFillable ? '<button class="btn btn-primary btn-sm" type="button" data-action="apply-purchase-order-match">确认补入空值</button>' : ""}
      </div>
    `);
  }

  renderPurchaseOrderMatchRows(sourceRows, writeback) {
    if (!sourceRows.length) {
      return '<tr><td colspan="7" class="ocw-purchase-empty-line">未识别到包含物料编码、数量、单价和货值的完整明细</td></tr>';
    }
    const matchedRows = writeback.matched_rows || [];
    const unmatchedRows = writeback.unmatched_rows || [];
    return sourceRows
      .map((source) => {
        const materialCode = String(source.material_code || "");
        const matched = matchedRows.find((row) => String((row.mapped_row || {}).material_code || "") === materialCode);
        const unmatched = unmatchedRows.some((row) => String(row.material_code || "") === materialCode);
        let status = "未匹配";
        let statusClass = "ocw-match-missing";
        if (matched && matched.has_conflict) {
          status = "已有不同采购值";
          statusClass = "ocw-match-conflict";
        } else if (matched && matched.has_fillable) {
          status = "可补入空值";
          statusClass = "ocw-match-ready";
        } else if (matched && matched.all_business_same) {
          status = "系统已有一致数据";
          statusClass = "ocw-match-same";
        } else if (matched) {
          status = "无需补入";
          statusClass = "ocw-match-same";
        } else if (!unmatched) {
          status = "待核对";
        }
        return `
          <tr>
            <td>${this.escape(materialCode || "--")}</td>
            <td>${this.escape(source.product_name || "--")}</td>
            <td>${this.escape(this.formatNumber(source.quantity))}</td>
            <td>${this.escape(this.formatNumber(source.unit_price))}</td>
            <td>${this.escape(source.purchase_currency || "--")}</td>
            <td>${this.escape(this.formatNumber(source.goods_value))}</td>
            <td><span class="ocw-match-status ${statusClass}">${this.escape(status)}</span></td>
          </tr>
        `;
      })
      .join("");
  }

  async applyPurchaseOrderMatch(dialog, attachmentName, batch = null, attachmentListDialog = null, sourcePreviewDialog = null, $button = null) {
    if ($button && $button.length) {
      $button.prop("disabled", true).text("提交中");
    }
    try {
      const confirmed = await new Promise((resolve) => {
        frappe.confirm(
          "将只补入总表中为空的采购单价、币种和货值；系统已有不同值不会覆盖。",
          () => resolve(true),
          () => resolve(false)
        );
      });
      if (!confirmed) return;
      const result = await this.call(
        "overseas_costing.api.import_api.apply_oa_purchase_order_fillable_fields",
        { attachment_name: attachmentName, recalculate_after_writeback: 1 },
        true
      );
      if (!result || !result.ok) {
        this.showPendingFeature((result && result.message) || "采购订单字段写入失败。");
        return;
      }
      frappe.show_alert({ message: result.message || "采购订单空值已补入", indicator: "green" });
      if (batch && attachmentListDialog) {
        await this.loadOaFormAttachments(batch, attachmentListDialog);
        await this.refreshBatch(batch.name);
      }
      if (sourcePreviewDialog) sourcePreviewDialog.hide();
      dialog.hide();
    } finally {
      if ($button && $button.length && dialog.$wrapper.is(":visible")) {
        $button.prop("disabled", false).text("确认补入空值");
      }
    }
  }

  async parseCurrentOaAttachments(batch, dialog, $button = null) {
    if (!batch || this.isParsingOaAttachments) return;
    this.isParsingOaAttachments = true;
    if ($button && $button.length) {
      $button.prop("disabled", true).text("解析中");
    }
    try {
      const result = await this.call(
        "overseas_costing.api.import_api.parse_oa_source_attachments",
        {
          batch_name: batch.name,
          limit: 80,
          skip_parsed: 1,
          recalculate: 1,
        },
        true
      );
      if (!result || !result.ok) {
        this.showOaAttachmentParseResult(result || { ok: false, message: "当前批次附件解析失败。" });
      } else {
        frappe.show_alert({ message: result.message || "当前批次可处理附件已解析", indicator: "green" });
      }
      await this.loadOaFormAttachments(batch, dialog);
      await this.refreshBatch(batch.name);
    } finally {
      this.isParsingOaAttachments = false;
      if ($button && $button.length) {
        $button.prop("disabled", false).text("附件处理");
      }
    }
  }

  showOaAttachmentParseResult(result = {}) {
    const items = Array.isArray(result.items) ? result.items : [];
    const failedItems = items.filter((item) => item.action === "failed" || item.action === "blocked");
    const skippedItems = items.filter((item) => item.action === "skipped");
    const summaryCards = [
      ["扫描附件", result.scanned_count || 0],
      ["已下载", result.downloaded_count || 0],
      ["已解析", result.parsed_count || 0],
      ["装箱单", result.packing_parsed_count || 0],
      ["内容识别", result.source_recognized_count || 0],
      ["新增物料", result.created_count || 0],
      ["写入字段", result.changed_field_count || 0],
      ["失败", result.failed_count || 0],
      ["跳过", result.skipped_count || 0],
    ]
      .map(
        ([label, value]) => `
          <div>
            <span>${this.escape(label)}</span>
            <strong>${this.escape(String(value))}</strong>
          </div>
        `
      )
      .join("");
    const failedRows = failedItems.length
      ? failedItems
          .map(
            (item) => `
              <tr>
                <td>${this.escape(item.file_name || item.attachment_name || "--")}</td>
                <td>${this.escape(this.attachmentTypeLabel(item.attachment_type))}</td>
                <td>${this.escape(this.oaAttachmentParseActionLabel(item))}</td>
                <td>${this.escape(item.reason || (item.download && item.download.message) || "--")}</td>
              </tr>
            `
          )
          .join("")
      : `<tr><td colspan="4" class="ocw-parse-result-empty">暂无失败附件</td></tr>`;
    const skippedText = skippedItems.length
      ? `另有 ${skippedItems.length} 个附件暂未处理，通常是非装箱单 Excel 或暂不支持格式。`
      : "";
    const fileAccessNote = result.file_access_blocked_count
      ? "当前账号没有部分钉钉附件的文件级访问权限。请换成能在钉钉原单打开附件的账号，或手动下载后拖放上传。"
      : "";
    const dialog = new frappe.ui.Dialog({
      title: "附件解析结果",
      size: "large",
      fields: [
        {
          fieldtype: "HTML",
          fieldname: "parse_result",
          options: `
            <div class="ocw-parse-result">
              <div class="ocw-purchase-summary">${summaryCards}</div>
              <div class="ocw-purchase-note">${this.escape(result.message || "当前批次附件解析未完成。")}</div>
              ${fileAccessNote ? `<div class="ocw-confirm-note">${this.escape(fileAccessNote)}</div>` : ""}
              ${skippedText ? `<div class="ocw-parse-result-muted">${this.escape(skippedText)}</div>` : ""}
              <div class="ocw-purchase-table-wrap">
                <table class="ocw-purchase-table ocw-parse-result-table">
                  <thead>
                    <tr>
                      <th>附件</th>
                      <th>类型</th>
                      <th>状态</th>
                      <th>原因</th>
                    </tr>
                  </thead>
                  <tbody>${failedRows}</tbody>
                </table>
              </div>
            </div>
          `,
        },
      ],
      primary_action_label: "我知道了",
      primary_action: () => dialog.hide(),
    });
    dialog.show();
    dialog.$wrapper.addClass("ocw-purchase-modal ocw-oa-parse-result-modal");
  }

  oaAttachmentParseActionLabel(item = {}) {
    if (item.error_type === "dingtalk_attachment_file_access") return "无附件访问权";
    if (item.error_type === "dingtalk_permission") return "缺少钉钉权限";
    if (item.action === "blocked") return "已暂停";
    if (item.action === "failed") return "失败";
    if (item.action === "skipped") return "已跳过";
    if (item.action === "parsed") return "已解析";
    return item.action || "--";
  }

  renderOaAttachmentList(items) {
    if (!items.length) {
      return `
        <section class="ocw-purchase-section">
          <h4>发起附件清单</h4>
          <div class="ocw-purchase-empty-line">暂无发起附件记录</div>
        </section>
      `;
    }
    const downloadableCount = items.filter((row) => {
      const error = row.last_download_error && row.last_download_error.error_type;
      return !row.file_url && !error && (row.can_download || row.file_id);
    }).length;
    const downloadedCount = items.filter((row) => row.file_url).length;
    const downloadFailedCount = items.filter((row) => row.last_download_error && row.last_download_error.error_type).length;
    const rows = items
      .map((row, index) => {
        const recognizedType = String(row.recognized_type || "").trim();
        const recognizedTypeLabel = recognizedType && recognizedType !== "unclassified" ? row.recognized_type_label : "";
        const typeLabel = row.confirmed_type_label || recognizedTypeLabel || this.attachmentTypeLabel(row.attachment_type);
        const downloadError = row.last_download_error && row.last_download_error.error_type ? row.last_download_error : null;
        const savedFileRef = row.file_url
          ? "已保存，可预览或下载原件"
          : downloadError
            ? this.attachmentDownloadErrorLabel(downloadError)
            : "";
        const actions = [];
        if (row.file_url) {
          actions.push(`
            <a
              class="ocw-link-btn"
              href="${this.escape(row.file_url)}"
              download="${this.escape(row.file_name || "")}"
              target="_self"
            >下载到本地</a>
          `);
          actions.push(`
            <button
              class="ocw-link-btn"
              data-action="preview-oa-attachment-file"
              data-attachment-name="${this.escape(row.name || "")}"
              data-file-url="${this.escape(row.file_url || "")}"
              data-file-name="${this.escape(row.file_name || "")}"
            >附件预览</button>
          `);
        } else if (row.can_download || row.file_id) {
          actions.push(`
            <button
              class="ocw-link-btn"
              data-action="download-oa-attachment"
              data-attachment-name="${this.escape(row.name || "")}"
              data-open-parse-after-download="0"
            >${downloadError ? "重试下载" : "下载到本地"}</button>
          `);
          actions.push(`
            <button
              class="ocw-link-btn"
              data-action="preview-oa-attachment-file"
              data-attachment-name="${this.escape(row.name || "")}"
              data-file-name="${this.escape(row.file_name || "")}"
            >附件预览</button>
          `);
          if (downloadError) {
            actions.push(`<span class="ocw-purchase-source-disabled">${this.escape(this.attachmentDownloadActionHint(downloadError))}</span>`);
          }
        } else {
          actions.push(`<span class="ocw-purchase-source-disabled">待下载</span>`);
        }
        return `
          <tr>
            <td>${this.escape(String(index + 1))}</td>
            <td title="${this.escape(row.file_name || "")}">
              <div class="ocw-attachment-file-name">${this.escape(row.file_name || "--")}</div>
              ${savedFileRef ? `<div class="ocw-attachment-file-url">${this.escape(savedFileRef)}</div>` : ""}
            </td>
            <td>${this.escape(typeLabel)}</td>
            <td>${this.escape(this.attachmentStatusLabel(row.parse_status, row))}</td>
            <td>${this.escape(this.attachmentPurposeLabel(row))}</td>
            <td><div class="ocw-attachment-actions">${actions.join("")}</div></td>
          </tr>
        `;
      })
      .join("");
    return `
      <section class="ocw-purchase-section">
        <h4>发起附件清单</h4>
        <div class="ocw-confirm-note">这些是钉钉审批发起人提交的附件。请按资料类型查看和核对；评论附件暂不处理。</div>
        <div class="ocw-confirm-note">已登记 ${this.escape(String(items.length))} 个发起附件，${this.escape(String(downloadableCount))} 个待从钉钉下载，${this.escape(String(downloadedCount))} 个已保存，${this.escape(String(downloadFailedCount))} 个下载受限。</div>
        <div class="ocw-purchase-table-wrap">
          <table class="ocw-purchase-table ocw-attachment-table">
            <colgroup>
              <col class="ocw-col-index">
              <col class="ocw-col-file">
              <col class="ocw-col-type">
              <col class="ocw-col-status">
              <col class="ocw-col-purpose">
              <col class="ocw-col-action">
            </colgroup>
            <thead>
              <tr>
                <th>#</th>
                <th>文件名</th>
                <th>类型</th>
                <th>状态</th>
                <th>用途</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </section>
    `;
  }

  attachmentDownloadErrorLabel(error = {}) {
    if (error.error_type === "dingtalk_attachment_file_access") return "下载失败：当前账号无附件访问权";
    if (error.error_type === "dingtalk_attachment_permission") return "下载失败：应用权限不足";
    if (error.error_type === "dingtalk_attachment_user") return "下载失败：下载账号不可用";
    return "下载失败：请查看原因后重试";
  }

  attachmentDownloadActionHint(error = {}) {
    if (error.error_type === "dingtalk_attachment_file_access") return "换可访问账号后重试";
    if (error.error_type === "dingtalk_attachment_permission") return "开通权限后重试";
    if (error.error_type === "dingtalk_attachment_user") return "配置账号后重试";
    return "处理后重试";
  }

  attachmentTypeLabel(type) {
    const labels = {
      "Packing List": "装箱单",
      "Tax Certificate": "完税凭证",
      "Logistics Bill": "物流账单",
      "Commercial Invoice": "商业发票",
      "Purchase Order": "采购订单",
      "Customs Declaration": "报关资料",
      Other: "待识别",
    };
    return labels[type] || type || "待识别";
  }

  attachmentPurposeLabel(row = {}) {
    const confirmedType = String((row.manual_review && row.manual_review.confirmed_type) || "").trim();
    const recognizedType = String(row.recognized_type || "").trim();
    const type = confirmedType || (recognizedType && recognizedType !== "unclassified" ? recognizedType : "") || String(row.attachment_type || "").trim();
    const purposes = {
      "Packing List": "核对实际数量、重量和体积",
      "Purchase Order": "核对采购单价、币种和货值",
      purchase_order: "核对采购单价、币种和货值",
      purchase_price_document: "核对采购价格信息",
      "Customs Declaration": "核对报关单号和海关信息",
      customs_declaration: "核对报关单号和海关信息",
      "Logistics Bill": "核对物流费用",
      logistics_quote: "核对物流费用",
      "Tax Certificate": "核对最终税费",
      "Commercial Invoice": "核对发票号、货值和币种",
      "Excel Main Table": "核对货物明细",
      other: "保留原件备查",
      Other: "保留原件备查",
    };
    return purposes[type] || "待人工判断用途";
  }

  attachmentStatusLabel(status, row = {}) {
    if (row.manual_review && row.manual_review.status === "confirmed") return "已人工确认";
    if (row.last_download_error && row.last_download_error.error_type) {
      if (row.last_download_error.error_type === "dingtalk_attachment_file_access") return "下载失败（无访问权）";
      return "下载失败";
    }
    const normalized = String(status || "").trim().toLowerCase();
    if (row.file_url) return "已保存";
    if (normalized === "failed" || normalized === "error") return "待复核";
    if (normalized === "queued") return "待下载";
    if (!normalized) return "待下载";
    return status;
  }

  attachmentParseTargetLabel(target) {
    const labels = {
      actual_shipped_qty: "实际发货数量",
      gross_weight_kg: "毛重KG",
      volume_m3: "体积m3",
      volume_weight_kg: "体积重KG",
      chargeable_weight_kg: "计费重KG",
      pedimento_no: "报关单号",
      tax_totals: "税费合计",
      paid_total_mxn: "实缴金额MXN",
      line_items: "明细行",
      logistics_fee: "物流费用",
      fuel_surcharge: "燃油附加费",
      currency: "币种",
      bill_total: "账单总额",
      invoice_no: "发票号",
      goods_value: "货值",
      unit_price: "采购单价",
      purchase_currency: "采购币种",
      customs_declaration: "报关资料",
    };
    return labels[target] || target || "";
  }

  openPackingListPreviewDialog(batchName = "", attachmentName = "", fileUrl = "") {
    const batch = batchName ? this.findBatch(batchName) : this.getActiveBatch();
    if (!batch) {
      this.showPendingFeature("当前没有可解析装箱单的批次。");
      return;
    }
    if (!fileUrl) {
      this.showPendingFeature("当前附件只有钉钉文件标识，还没有下载到系统文件地址，暂不能解析。");
      return;
    }
    this.activeBatchName = batch.name;
    const batchLabel = batch.batch_no || batch.waybill_no || batch.name;
    const dialog = new frappe.ui.Dialog({
      title: "装箱单解析预览",
      size: "large",
      fields: [
        {
          fieldtype: "HTML",
          fieldname: "packing_preview",
          options: `
            <div class="ocw-purchase-preview" data-area="packing-preview">
              <div class="ocw-purchase-target">
                <span>当前批次</span>
                <strong>${this.escape(batchLabel)}</strong>
                <em>先预览匹配结果，不会直接写入实际数量、毛重和体积。</em>
              </div>
              <div class="ocw-purchase-loading">正在解析装箱单</div>
            </div>
          `,
        },
      ],
      primary_action_label: "关闭",
      primary_action: () => dialog.hide(),
    });
    dialog.show();
    dialog.$wrapper.addClass("ocw-purchase-modal ocw-packing-preview-modal");
    this.loadPackingListPreview(batch, dialog, attachmentName, fileUrl).catch((error) => {
      dialog.$wrapper.find("[data-area='packing-preview']").html(`
        <div class="ocw-purchase-empty">
          <strong>装箱单解析预览失败</strong>
          <span>${this.escape(this.normalizeErrorMessage(error))}</span>
        </div>
      `);
    });
  }

  async loadPackingListPreview(batch, dialog, attachmentName, fileUrl) {
    const result = await this.call(
      "overseas_costing.api.import_api.preview_packing_list_attachment",
      {
        batch_name: batch.name,
        version_name: batch.current_version || null,
        attachment_name: attachmentName || null,
        file_url: fileUrl || null,
      },
      true
    );
    this.renderPackingListPreview(dialog, result, batch, attachmentName, fileUrl);
  }

  renderPackingListPreview(dialog, result, batch, attachmentName, fileUrl) {
    const $target = dialog.$wrapper.find("[data-area='packing-preview']");
    if (!result || !result.ok) {
      $target.html(`
        <div class="ocw-purchase-empty">
          <strong>暂时无法解析装箱单</strong>
          <span>${this.escape((result && result.message) || "请确认附件已经下载为 Excel 文件。")}</span>
        </div>
      `);
      return;
    }

    const preview = result.writeback_preview || {};
    const matchedRows = preview.matched_rows || [];
    const fillableRows = matchedRows.filter((row) => row.has_fillable);
    const conflictRows = matchedRows.filter((row) => row.has_conflict);
    const unmatchedRows = preview.unmatched_rows || [];
    const ambiguousRows = preview.ambiguous_rows || [];
    const parser = result.parser_meta || {};

    $target.html(`
      <div class="ocw-purchase-target">
        <span>当前批次</span>
        <strong>${this.escape(batch.batch_no || batch.waybill_no || batch.name)}</strong>
        <em>${this.escape(result.message || "装箱单预览已完成，当前未写入数据。")}</em>
      </div>
      <div class="ocw-purchase-summary">
        <div><span>解析行数</span><strong>${this.escape(String(result.mapped_preview_count || 0))}</strong></div>
        <div><span>匹配行</span><strong>${this.escape(String(preview.matched_count || 0))}</strong></div>
        <div><span>可写入</span><strong>${this.escape(String(preview.fillable_row_count || 0))}</strong></div>
        <div><span>未匹配</span><strong>${this.escape(String(preview.unmatched_count || 0))}</strong></div>
      </div>
      <div class="ocw-purchase-note">
        来源附件已与当前批次物料核对；只补当前为空或为 0 的实际发货数量、毛重、体积、计费重。
      </div>
      ${this.renderPackingApplyAction(preview)}
      ${this.renderPurchasePreviewSection("可写入装箱单字段", fillableRows, "fillable")}
      ${this.renderPackingConflictSection(conflictRows)}
      ${this.renderPackingUnmatchedSection(unmatchedRows, ambiguousRows)}
    `);
    dialog.$wrapper
      .off("click.ocwPackingPreview")
      .on("click.ocwPackingPreview", "[data-action='apply-packing-fillable']", () => {
        this.applyPackingListFillableFields(batch, dialog, result, attachmentName, fileUrl).catch((error) => this.showError(error));
      })
      .on("click.ocwPackingPreview", "[data-action='resolve-packing-conflict']", (event) => {
        this.resolvePackingConflictRow(
          batch,
          dialog,
          attachmentName,
          fileUrl,
          $(event.currentTarget).attr("data-target-item-name"),
          $(event.currentTarget).attr("data-resolution-action"),
          $(event.currentTarget)
        ).catch((error) => this.showError(error));
      });
  }

  renderPackingApplyAction(preview = {}) {
    const fillableCount = Number(preview.fillable_row_count || 0);
    if (!fillableCount) return "";
    return `
      <div class="ocw-purchase-apply">
        <div>
          <strong>写入可补装箱单字段</strong>
          <span>本次可写入 ${this.escape(String(fillableCount))} 行，只补空值或 0 值；已有差异的行不自动覆盖。</span>
        </div>
        <button class="ocw-primary-btn ocw-mini-btn" data-action="apply-packing-fillable">写入可补字段</button>
      </div>
    `;
  }

  renderPackingConflictSection(conflictRows = []) {
    if (!conflictRows.length) {
      return `
        <section class="ocw-purchase-section">
          <h4>待处理差异</h4>
          <div class="ocw-purchase-empty-line">暂无需要人工处理的差异</div>
        </section>
      `;
    }
    const body = conflictRows
      .map((row) => {
        const conflicts = (row.business_changes || []).filter((change) => change.status === "conflict");
        const values = conflicts
          .map(
            (change) => `
              <div class="ocw-packing-conflict-value">
                <strong>${this.escape(change.field_label || change.field_name || "字段")}</strong>
                <span>系统：${this.escape(this.formatValue(change.old_value) || "空")}</span>
                <span>附件：${this.escape(this.formatValue(change.new_value) || "空")}</span>
              </div>
            `
          )
          .join("");
        const resolution = row.conflict_resolution || {};
        const resolutionText = resolution.action_label
          ? `<div class="ocw-packing-resolution-status">当前处理：${this.escape(resolution.action_label)}</div>`
          : "";
        return `
          <tr>
            <td>${this.escape(String(row.target_row_no || "--"))}</td>
            <td>${this.escape(row.target_material_code || "--")}</td>
            <td title="${this.escape(row.target_product_name || "")}">${this.escape(row.target_product_name || "--")}</td>
            <td>${values || "--"}${resolutionText}</td>
            <td>
              <div class="ocw-packing-conflict-actions">
                <button class="ocw-link-btn" type="button" data-action="resolve-packing-conflict" data-target-item-name="${this.escape(row.target_item_name || "")}" data-resolution-action="use_attachment">采用附件值</button>
                <button class="ocw-link-btn" type="button" data-action="resolve-packing-conflict" data-target-item-name="${this.escape(row.target_item_name || "")}" data-resolution-action="keep_system">保留系统值</button>
                <button class="ocw-link-btn" type="button" data-action="resolve-packing-conflict" data-target-item-name="${this.escape(row.target_item_name || "")}" data-resolution-action="pending_review">待核对</button>
              </div>
            </td>
          </tr>
        `;
      })
      .join("");
    return `
      <section class="ocw-purchase-section">
        <h4>待处理差异</h4>
        <div class="ocw-purchase-table-wrap">
          <table class="ocw-purchase-table ocw-packing-conflict-table">
            <thead><tr><th>行号</th><th>物料编码</th><th>系统品名</th><th>系统值与附件值</th><th>处理</th></tr></thead>
            <tbody>${body}</tbody>
          </table>
        </div>
      </section>
    `;
  }

  async resolvePackingConflictRow(batch, dialog, attachmentName, fileUrl, targetItemName, resolutionAction, $button = null) {
    const actionLabels = {
      use_attachment: "采用附件值",
      keep_system: "保留系统值",
      pending_review: "待核对",
    };
    if (!targetItemName || !actionLabels[resolutionAction]) {
      this.showPendingFeature("缺少差异处理信息。");
      return;
    }
    if (resolutionAction === "use_attachment") {
      const confirmed = await new Promise((resolve) => {
        frappe.confirm(
          "采用附件值将覆盖当前物料行的系统值，并触发重新试算。",
          () => resolve(true),
          () => resolve(false)
        );
      });
      if (!confirmed) return;
    }
    if ($button && $button.length) {
      $button.prop("disabled", true).text("处理中");
    }
    try {
      const result = await this.call(
        "overseas_costing.api.import_api.resolve_packing_list_conflict_row",
        {
          batch_name: batch.name,
          version_name: batch.current_version || null,
          attachment_name: attachmentName || null,
          file_url: fileUrl || null,
          target_item_name: targetItemName,
          resolution_action: resolutionAction,
          recalculate_after_writeback: 1,
        },
        true
      );
      if (!result || !result.ok) {
        throw new Error((result && result.message) || "保存差异处理结果失败");
      }
      await this.loadBatchItems(batch.name, batch.current_version, true);
      await this.loadAuditLogs(batch.name, batch.current_version);
      this.expandedBatchNames.add(batch.name);
      this.renderTable();
      this.renderDiffPanel();
      frappe.show_alert({ message: result.message || `${actionLabels[resolutionAction]}已保存`, indicator: "green" });
      await this.loadPackingListPreview(batch, dialog, attachmentName, fileUrl);
    } finally {
      if ($button && $button.length && dialog.$wrapper.is(":visible")) {
        $button.prop("disabled", false).text(actionLabels[resolutionAction]);
      }
    }
  }

  renderPackingUnmatchedSection(unmatchedRows = [], ambiguousRows = []) {
    const rows = [
      ...ambiguousRows.map((row) => ({
        ...(row.mapped_row || {}),
        source_row_no: row.source_row_no,
        reason: row.reason || `匹配到多行：${(row.candidate_row_nos || []).join("、")}`,
        suggestion: row.suggestion || "补齐规格、数量或物料编码后重新解析。",
      })),
      ...unmatchedRows.map((row) => ({
        ...row,
        reason: row.reason || "当前批次没有匹配物料，未写入",
        suggestion: row.suggestion || "确认属于本批次后，可先新增物料或修正编码再解析。",
      })),
    ];
    if (!rows.length) {
      return `
        <section class="ocw-purchase-section">
          <h4>未匹配装箱单行</h4>
          <div class="ocw-purchase-empty-line">暂无未匹配行</div>
        </section>
      `;
    }
    const body = rows
      .map(
        (row) => `
          <tr>
            <td>${this.escape(row.source_row_no || row.excel_row_no || "--")}</td>
            <td>${this.escape(row.material_code || "--")}</td>
            <td title="${this.escape(row.product_name || "")}">${this.escape(row.product_name || "--")}</td>
            <td title="${this.escape(row.spec_model || "")}">${this.escape(row.spec_model || "--")}</td>
            <td>${this.escape(this.formatValue(row.actual_shipped_qty) || "--")}</td>
            <td>${this.escape(this.formatValue(row.gross_weight_kg) || "--")}</td>
            <td>${this.escape(this.formatValue(row.volume_m3) || "--")}</td>
            <td>${this.renderReasonCell(row)}</td>
          </tr>
        `
      )
      .join("");
    return `
      <section class="ocw-purchase-section">
        <h4>未匹配装箱单行</h4>
        <div class="ocw-purchase-table-wrap">
          <table class="ocw-purchase-table">
            <thead>
              <tr>
                <th>来源行</th>
                <th>物料编码</th>
                <th>品名</th>
                <th>规格</th>
                <th>实际数量</th>
                <th>毛重 KG</th>
                <th>体积 m3</th>
                <th>原因</th>
              </tr>
            </thead>
            <tbody>${body}</tbody>
          </table>
        </div>
      </section>
    `;
  }

  async applyPackingListFillableFields(batch, dialog, previewResult, attachmentName, fileUrl) {
    const preview = (previewResult && previewResult.writeback_preview) || {};
    const fillableCount = Number(preview.fillable_row_count || 0);
    if (!fillableCount) {
      frappe.show_alert({ message: "当前没有可写入的装箱单字段", indicator: "blue" });
      return;
    }
    const confirmed = await new Promise((resolve) => {
      frappe.confirm(
        `
          <div class="ocw-confirm-copy">
            <h4>确认写入装箱单字段？</h4>
            <p>本次最多写入 ${this.escape(String(fillableCount))} 行实际发货数量、毛重、体积或计费重。</p>
            <div class="ocw-confirm-note">只补空值或 0 值；已有差异的行不会自动覆盖。</div>
          </div>
        `,
        () => resolve(true),
        () => resolve(false)
      );
    });
    if (!confirmed) return;

    const $button = dialog.$wrapper.find("[data-action='apply-packing-fillable']");
    $button.prop("disabled", true).text("写入中");
    try {
      const result = await this.call(
        "overseas_costing.api.import_api.apply_packing_list_fillable_fields",
        {
          batch_name: batch.name,
          version_name: batch.current_version || null,
          attachment_name: attachmentName || null,
          file_url: fileUrl || null,
        },
        true
      );
      if (!result.ok) {
        throw new Error(result.message || "装箱单字段写入失败");
      }
      if (Number(result.updated_count || 0) > 0) {
        this.markBatchDirty(batch.name);
      }
      await this.loadBatchItems(batch.name, batch.current_version, true);
      await this.loadAuditLogs(batch.name, batch.current_version);
      this.expandedBatchNames.add(batch.name);
      this.renderTable();
      this.renderDiffPanel();
      if (this.activeOaAttachmentDialog && this.activeOaAttachmentDialog.$wrapper && this.activeOaAttachmentDialog.$wrapper.is(":visible")) {
        this.loadOaFormAttachments(batch, this.activeOaAttachmentDialog).catch((error) => this.showError(error));
      }
      frappe.show_alert({ message: result.message || "装箱单字段已写入", indicator: result.updated_count ? "green" : "blue" });
      dialog.hide();
    } finally {
      $button.prop("disabled", false).text("写入可补字段");
    }
  }

  openDingtalkLink(openUrl) {
    const url = String(openUrl || "").trim();
    if (!url) {
      this.showPendingFeature("当前审批单没有可打开的钉钉链接。");
      return;
    }
    if (url.startsWith("dingtalk://")) {
      window.location.href = url;
      frappe.show_alert({ message: "正在唤起钉钉客户端", indicator: "blue" });
      return;
    }
    this.openBrowserTab(url, "钉钉审批单");
  }

  openBrowserTab(url, title = "打开链接", preopenedWindow = null) {
    const targetUrl = String(url || "").trim();
    if (!targetUrl) return false;
    if (preopenedWindow && !preopenedWindow.closed) {
      preopenedWindow.location.href = targetUrl;
      return true;
    }
    const link = document.createElement("a");
    link.href = targetUrl;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.style.display = "none";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    return true;
  }

  closePreopenedWindow(preopenedWindow) {
    if (preopenedWindow && !preopenedWindow.closed) {
      preopenedWindow.close();
    }
  }

  renderPurchasePreviewSection(title, rows, type) {
    if (!rows.length) {
      return `
        <section class="ocw-purchase-section">
          <h4>${this.escape(title)}</h4>
          <div class="ocw-purchase-empty-line">暂无${type === "fillable" ? "可写入" : "差异"}行</div>
        </section>
      `;
    }
    const body = rows
      .map((row) => {
        const changes = (row.business_changes || [])
          .map((change) => {
            const status = this.purchaseChangeLabel(change.status);
            return `
              <span class="ocw-purchase-change ${this.escape(change.status || "")}">
                ${this.escape(change.field_label || change.field_name)}：${this.escape(this.formatValue(change.old_value) || "空")} -> ${this.escape(this.formatValue(change.new_value) || "空")}（${this.escape(status)}）
              </span>
            `;
          })
          .join("");
        return `
          <tr>
            <td>${this.escape(String(row.target_row_no || "--"))}</td>
            <td>${this.escape(row.target_material_code || "--")}</td>
            <td title="${this.escape(row.target_product_name || "")}">${this.escape(row.target_product_name || "--")}</td>
            <td title="${this.escape(row.target_spec_model || "")}">${this.escape(row.target_spec_model || "--")}</td>
            <td>${changes || "--"}</td>
          </tr>
        `;
      })
      .join("");
    return `
      <section class="ocw-purchase-section">
        <h4>${this.escape(title)}</h4>
        <div class="ocw-purchase-table-wrap">
          <table class="ocw-purchase-table">
            <thead>
              <tr>
                <th>行号</th>
                <th>物料编码</th>
                <th>系统品名</th>
                <th>系统规格</th>
                <th>预览变化</th>
              </tr>
            </thead>
            <tbody>${body}</tbody>
          </table>
        </div>
      </section>
    `;
  }

  renderPurchaseUnmatchedSection(unmatchedRows, ambiguousRows) {
    const rows = [
      ...ambiguousRows.map((row) => ({
        ...row.mapped_row,
        source_row_no: row.source_row_no,
        reason: row.reason || `匹配到多行：${(row.candidate_row_nos || []).join("、")}`,
        suggestion: row.suggestion || "补齐规格或数量后重新匹配。",
      })),
      ...unmatchedRows.map((row) => ({
        ...row,
        reason: row.reason || "当前批次没有该物料编码，未写入",
        suggestion: row.suggestion || "确认属于本批次后，可先新增物料或修正编码再解析。",
      })),
    ];
    if (!rows.length) {
      return `
        <section class="ocw-purchase-section">
          <h4>未匹配采购行</h4>
          <div class="ocw-purchase-empty-line">暂无未匹配行</div>
        </section>
      `;
    }
    const body = rows
      .map(
        (row) => `
          <tr>
            <td>${this.escape(row.source_row_no || row.excel_row_no || "--")}</td>
            <td>${this.escape(row.material_code || "--")}</td>
            <td title="${this.escape(row.product_name || "")}">${this.escape(row.product_name || "--")}</td>
            <td title="${this.escape(row.spec_model || "")}">${this.escape(row.spec_model || "--")}</td>
            <td>${this.escape(this.formatValue(row.unit_price) || "--")}</td>
            <td>${this.escape(row.purchase_currency || "--")}</td>
            <td>${this.escape(row.source_approval_no || "--")}</td>
            <td>${this.renderReasonCell(row)}</td>
          </tr>
        `
      )
      .join("");
    return `
      <section class="ocw-purchase-section">
        <h4>未匹配采购行</h4>
        <div class="ocw-purchase-table-wrap">
          <table class="ocw-purchase-table">
            <thead>
              <tr>
                <th>来源行</th>
                <th>物料编码</th>
                <th>采购品名</th>
                <th>采购规格</th>
                <th>单价</th>
                <th>币种</th>
                <th>采购审批</th>
                <th>原因</th>
              </tr>
            </thead>
            <tbody>${body}</tbody>
          </table>
        </div>
      </section>
    `;
  }

  renderReasonCell(row = {}) {
    const reason = row.reason || "--";
    const suggestion = row.suggestion || "";
    return `
      <div class="ocw-match-reason">
        <strong>${this.escape(reason)}</strong>
        ${suggestion ? `<small>${this.escape(suggestion)}</small>` : ""}
      </div>
    `;
  }

  purchaseChangeLabel(status) {
    const labels = {
      fillable: "可写入",
      conflict: "有差异",
      same: "一致",
      empty_source: "来源为空",
    };
    return labels[status] || status || "未知";
  }

  async openDingtalkOrder(batchName = "") {
    const batch = batchName ? this.findBatch(batchName) : this.getActiveBatch();
    if (!batch) {
      this.showPendingFeature("当前没有可打开的批次。");
      return;
    }
    this.activeBatchName = batch.name;
    if (this.isOpeningDingtalk) return;
    this.isOpeningDingtalk = true;
    let preopenedWindow = null;
    try {
      preopenedWindow = window.open("about:blank", "_blank");
      if (preopenedWindow) {
        preopenedWindow.opener = null;
      }
      const result = await this.call("overseas_costing.api.batch.get_dingtalk_order_link", {
        batch_name: batch.name,
      });
      const order = result.dingtalk_order || {};
      if (!order.can_open || !order.open_url) {
        this.closePreopenedWindow(preopenedWindow);
        this.showPendingFeature("当前批次还没有关联钉钉审批链接，请先从国际物流单或采购支出单补来源信息。");
        return;
      }

      if (order.open_mode === "desktop_protocol") {
        this.closePreopenedWindow(preopenedWindow);
        window.location.href = order.open_url;
        frappe.show_alert({ message: "正在唤起钉钉客户端", indicator: "blue" });
        return;
      }

      if (!this.openBrowserTab(order.open_url, "钉钉订单", preopenedWindow)) {
        frappe.msgprint({
          title: "钉钉订单",
          message: `浏览器拦截了新窗口，请点击链接打开：<br><a href="${this.escape(order.open_url)}" target="_blank" rel="noopener noreferrer">${this.escape(order.open_url)}</a>`,
          indicator: "orange",
        });
      }
    } catch (error) {
      this.closePreopenedWindow(preopenedWindow);
      this.showError(error);
    } finally {
      this.isOpeningDingtalk = false;
    }
  }

  showPendingFeature(message) {
    frappe.show_alert({ message, indicator: "orange" });
  }

  setBatchLoading() {
    this.setTableLoading();
  }

  setTableLoading() {
    this.$root.find("[data-area='table']").html(`<div class="ocw-muted ocw-table-empty">加载中</div>`);
    this.$root.find("[data-area='table-count']").text("");
  }

  renderEmpty() {
    this.visibleBatches = [];
    this.batchItems = {};
    this.auditEvents = [];
    this.$root.find("[data-area='hierarchy-summary']").text("暂无批次");
    this.$root.find("[data-area='table']").html(`<div class="ocw-muted ocw-table-empty">暂无明细</div>`);
    this.$root.find("[data-area='table-title']").text("报关/运单层级列表");
    this.$root.find("[data-area='table-count']").text("");
    this.renderTransportWorkbench();
    this.renderAuditList();
    this.updateSearchResult();
    this.updateRecalculateAction();
  }

  renderBatchList() {
    this.renderTable();
  }

  renderTransportWorkbench() {
    if (!this.$root) return;
    const modes = this.transportWorkbenchModes();
    const scopeBatches = this.filterBatches({ ignoreTransport: true, ignoreBusinessType: true });
    const stats = this.transportWorkbenchStats(scopeBatches);
    const activeMode = String(this.filters.business_type || "").trim().toUpperCase();
    const totalCount = scopeBatches.length;
    this.$root
      .find("[data-action='set-transport-filter'][data-transport-mode='']")
      .toggleClass("active", !activeMode)
      .text(activeMode ? "全部" : `全部 ${totalCount}`);
    const html = modes
      .map((mode) => {
        const row = stats[mode.value] || { batchCount: 0, itemCount: 0 };
        const isActive = activeMode === mode.value;
        return `
          <button class="ocw-logistics-card ${isActive ? "active" : ""}" type="button" data-action="set-transport-filter" data-transport-mode="${this.escape(mode.value)}">
            <span>
              <strong>${this.escape(mode.label)}</strong>
              <em>${this.escape(mode.tip)}</em>
            </span>
            <b>${this.escape(String(row.batchCount))}</b>
            <small>${this.escape(String(row.itemCount))} 行物料</small>
          </button>
        `;
      })
      .join("");
    this.$root.find("[data-area='transport-workbench']").html(html);
  }

  transportWorkbenchModes() {
    return [
      { value: "SEA_STANDARD", label: "海运正报正清", tip: "主线核算" },
      { value: "SEA_DDP", label: "海运 DDP（双清包税）", tip: "包税双清" },
      { value: "AIR_DDP", label: "空运 DDP（双清包税）", tip: "包税双清" },
      { value: "AIR_STANDARD", label: "正常空运", tip: "运单与计费重量" },
      { value: "EXPRESS", label: "快递", tip: "面单与费用补齐" },
    ];
  }

  transportWorkbenchStats(batches = []) {
    const stats = this.transportWorkbenchModes().reduce((map, mode) => {
      map[mode.value] = { batchCount: 0, itemCount: 0 };
      return map;
    }, {});
    (batches || []).forEach((batch) => {
      const mode = this.batchBusinessType(batch, this.batchItems[batch.name] || []);
      if (!stats[mode]) return;
      stats[mode].batchCount += 1;
      stats[mode].itemCount += Number(batch.item_count || (this.batchItems[batch.name] || []).length || 0);
    });
    return stats;
  }

  renderBusinessEntityFilter() {
    const $select = this.$root.find("[data-filter='subsidiary_code']");
    if (!$select.length) return;
    const selected = String(this.filters.subsidiary_code || "");
    const values = this.businessEntityOptions.length
      ? this.businessEntityOptions.slice()
      : [...new Set(
          (this.batches || [])
            .map((batch) => String(batch.subsidiary_code || "").trim())
            .filter(Boolean)
        )].sort((left, right) => left.localeCompare(right, "zh-Hans-CN"));
    if (selected && !values.includes(selected)) values.push(selected);
    const signature = `${selected}\u0000${values.join("\u0000")}`;
    $select.prop("multiple", false).prop("size", 1).attr("size", "1");
    if (signature === this.businessEntityOptionsSignature) {
      $select.val(selected);
      return;
    }
    const options = [
      `<option value="">全部业务主体</option>`,
      ...values.map((value) => `<option value="${this.escape(value)}">${this.escape(value)}</option>`),
    ];
    $select.html(options.join("")).val(selected);
    this.businessEntityOptionsSignature = signature;
  }

  renderBusinessTypeFilter() {
    const $select = this.$root.find("[data-filter='business_type']");
    if (!$select.length) return;
    const selected = String(this.filters.business_type || "");
    const options = [
      `<option value="">全部业务类型</option>`,
      ...(this.businessTypeOptions || []).map((option) => {
        const value = typeof option === "string" ? option : option.value;
        const label = typeof option === "string" ? this.businessTypeLabel(option) : option.label;
        return `<option value="${this.escape(value)}">${this.escape(label)}</option>`;
      }),
    ];
    $select.html(options.join("")).val(selected);
  }

  renderSummary(detail) {
    const header = detail.header || {};
    const summary = detail.summary || {};
    const version = detail.version || {};
    const cells = [
      ["批次", header.batch_no],
      ["报关单号", header.customs_no],
      ["运单号", header.waybill_no],
      ["版本", this.versionLabel(version)],
      ["总货值", summary.total_goods_value || header.total_goods_value],
      ["毛重 KG", summary.total_gross_weight_kg || header.total_gross_weight_kg],
      ["综合成本 RMB", summary.total_cost_rmb || header.actual_total_cost_rmb || header.estimated_total_cost_rmb],
      ["行数", summary.item_count || header.item_count],
    ];
    this.$root.find("[data-area='summary']").html(`
      ${cells
        .map(
          ([label, value]) => `
            <div class="ocw-summary-cell">
              <span>${this.escape(label)}</span>
              <strong>${this.escape(this.formatValue(value))}</strong>
            </div>
          `
        )
        .join("")}
    `);
  }

  renderTable() {
    this.renderTransportWorkbench();
    this.updateWorkRoleSwitch();
    this.updateMainViewSwitch();
    if (this.erpQueueMode) {
      this.renderErpQueueTable();
      return;
    }
    const labels = this.parentTableLabels();
    const displayBatches = this.getDisplayedBatches();
    this.$root.find("[data-area='table-title']").text(labels.title);
    this.$root.find("[data-area='table-count']").text(`${displayBatches.length} 个${labels.blockName}`);
    this.renderBatchFocusControls();
    this.updateHierarchySummary();

    if (!displayBatches.length) {
      this.$root.find("[data-area='table']").html(`<div class="ocw-muted ocw-table-empty">${this.escape(this.workRoleInfo().empty)}</div>`);
      return;
    }

    const rows = displayBatches.map((batch) => this.renderBatchRows(batch)).join("");
    this.$root.find("[data-area='table']").html(`
      <table class="ocw-hierarchy-table">
        <colgroup>
        <col class="ocw-col-toggle" />
        <col class="ocw-col-waybill" />
        <col class="ocw-col-purchase-approval" />
        <col class="ocw-col-count" />
        <col class="ocw-col-state" />
        <col class="ocw-col-value" />
          <col class="ocw-col-money" />
          <col class="ocw-col-value" />
          <col class="ocw-col-voucher" />
          <col class="ocw-col-action" />
        </colgroup>
        <thead>
          <tr>
            <th></th>
            <th>${this.escape(labels.logisticsNo)}</th>
            <th>采购审批</th>
            <th>SKU数</th>
            <th>资料状态</th>
            <th>采购货值</th>
            <th>已识别费用</th>
            <th>综合成本</th>
            <th>凭证差异</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
      <div class="ocw-hierarchy-x-scroll" data-role="hierarchy-x-scroll" aria-label="层级列表横向滚动条">
        <div class="ocw-hierarchy-x-scroll-spacer" data-role="hierarchy-x-scroll-spacer"></div>
      </div>
    `);
    this.bindHierarchyScrollbars();
    this.renderDiffPanel();
    this.updateRecalculateAction();
  }

  updateMainViewSwitch() {
    if (!this.$root) return;
    this.$root.find("[data-action='set-main-view']").each((_, node) => {
      const $button = $(node);
      const view = $button.attr("data-view");
      $button.toggleClass("active", this.erpQueueMode ? view === "erp_queue" : view === "cost");
    });
  }

  updateWorkRoleSwitch() {
    if (!this.$root) return;
    const role = this.workRoleInfo();
    this.$root.find("[data-area='role-description']").first().text(role.description);
    this.$root.find("[data-area='table-title']").attr("title", role.description);
    this.$root.find("[data-action='set-work-role']").each((_, node) => {
      $(node).toggleClass("active", $(node).attr("data-role") === role.key);
    });
  }

  renderErpQueueTable() {
    const batches = this.getErpQueueBatches();
    this.$root.find("[data-area='table-title']").text("DeepLinkERP 待推送队列");
    this.$root.find("[data-area='table-count']").text(`${batches.length} 个批次`);
    this.renderBatchFocusControls();
    this.updateHierarchySummary();

    const filters = this.renderErpQueueFilters();
    if (!batches.length) {
      this.$root.find("[data-area='table']").html(`
        ${filters}
        <div class="ocw-muted ocw-table-empty">当前筛选下暂无 ERP 队列记录</div>
      `);
      this.renderDiffPanel();
      this.updateRecalculateAction();
      return;
    }

    const rows = batches.map((batch) => this.renderErpQueueRow(batch)).join("");
    this.$root.find("[data-area='table']").html(`
      ${filters}
      <table class="ocw-erp-queue-table">
        <thead>
          <tr>
            <th>批次</th>
            <th>业务主体</th>
            <th>版本</th>
            <th>物料数</th>
            <th>综合成本</th>
            <th>流程阶段</th>
            <th>回写状态</th>
            <th>生成时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    `);
    this.renderDiffPanel();
    this.updateRecalculateAction();
  }

  renderErpQueueFilters() {
    const options = [
      ["all", "全部"],
      ["not_started", "未开始"],
      ["pending", "待推送"],
      ["success", "成功"],
      ["failed", "失败"],
    ];
    const stats = this.erpQueueStats();
    return `
      <div class="ocw-erp-queue-toolbar">
        <div class="ocw-erp-queue-tabs">
          ${options
            .map(
              ([value, label]) => `
                <button class="${this.erpQueueStatus === value ? "active" : ""}" type="button" data-action="set-erp-queue-status" data-status="${this.escape(value)}">
                  ${this.escape(label)} <span>${this.escape(String(stats[value] || 0))}</span>
                </button>
              `
            )
            .join("")}
        </div>
        <p>这里展示本系统已试算、已校验、已生成报文和待正式接口推送的批次。</p>
      </div>
    `;
  }

  erpQueueStats() {
    const stats = { all: 0, not_started: 0, pending: 0, success: 0, failed: 0 };
    (this.visibleBatches || []).forEach((batch) => {
      const key = this.erpWritebackQueueKey(batch);
      stats.all += 1;
      stats[key] = (stats[key] || 0) + 1;
    });
    return stats;
  }

  getErpQueueBatches() {
    const source = this.visibleBatches || [];
    if (this.erpQueueStatus === "all") return source;
    return source.filter((batch) => this.erpWritebackQueueKey(batch) === this.erpQueueStatus);
  }

  erpWritebackQueueKey(batch = {}) {
    const value = String(batch.writeback_status || "Not Started").toLowerCase();
    if (value.includes("success")) return "success";
    if (value.includes("fail")) return "failed";
    if (value.includes("pending")) return "pending";
    return "not_started";
  }

  renderErpQueueRow(batch) {
    const items = this.batchItems[batch.name] || [];
    const hasLoadedItems = Object.prototype.hasOwnProperty.call(this.batchItems, batch.name);
    const itemCount = hasLoadedItems ? items.length : Number(batch.item_count || 0);
    const totalCost = this.batchTotalCostNumber(batch, items, hasLoadedItems);
    const writebackInfo = this.erpWritebackStatusInfo(batch);
    const stage = this.erpQueueStageInfo(batch, itemCount, totalCost);
    const batchLabel = batch.batch_no || batch.customs_no || batch.waybill_no || batch.name;
    const canPreview = String(batch.confirm_status || batch.status || "").toLowerCase().includes("confirmed");
    const canPush = canPreview && !String(batch.writeback_status || "").toLowerCase().includes("success");
    const previewTip = canPreview
      ? "点击预览 ERP 报文"
      : `${stage.label}：${stage.note || "先完成人工校验，再预览 ERP 报文"}`;
    return `
      <tr class="ocw-erp-queue-row" data-batch-name="${this.escape(batch.name)}">
        <td>
          <strong>${this.escape(batchLabel)}</strong>
          <span class="ocw-business-badge">${this.escape(this.businessTypeCompactLabel(batch.business_type))}</span>
        </td>
        <td>${this.escape(batch.subsidiary_code || "--")}</td>
        <td>${this.escape(batch.current_version || "--")}</td>
        <td class="ocw-num-cell">${this.escape(String(itemCount || 0))}</td>
        <td>${this.escape(this.isPositive(totalCost) ? `${this.formatNumber(totalCost)} RMB` : "--")}</td>
        <td><span class="ocw-queue-stage ${this.escape(stage.className)}">${this.escape(stage.label)}</span><small>${this.escape(stage.note)}</small></td>
        <td><span class="ocw-queue-status ${this.escape(writebackInfo.state)}">${this.escape(writebackInfo.label)}</span><small>${this.escape(batch.writeback_message || writebackInfo.note)}</small></td>
        <td>${this.escape(this.formatDateTimeMinute(batch.writeback_time) || "--")}</td>
        <td>
          <div class="ocw-row-action-group">
            <button class="ocw-outline-btn ocw-mini-btn" data-action="queue-open-batch" data-batch-name="${this.escape(batch.name)}">详情</button>
            <span class="ocw-tooltip-wrap" data-tooltip="${this.escape(previewTip)}" title="${this.escape(previewTip)}">
              ${
                canPreview
                  ? `<button class="ocw-outline-btn ocw-mini-btn" data-action="queue-preview-erp" data-batch-name="${this.escape(batch.name)}">预览</button>`
                  : `<button class="ocw-outline-btn ocw-mini-btn ocw-disabled-btn" type="button" disabled>预览</button>`
              }
            </span>
            <button class="ocw-outline-btn ocw-mini-btn" data-action="queue-writeback-erp" data-batch-name="${this.escape(batch.name)}"${canPush ? "" : " disabled"}>${this.erpWritebackQueueKey(batch) === "failed" ? "重试" : "生成"}</button>
          </div>
        </td>
      </tr>
    `;
  }

  erpQueueStageInfo(batch = {}, itemCount = 0, totalCost = 0) {
    const statusInfo = this.batchStatusInfo(batch.status, batch, itemCount);
    const confirmed = String(batch.confirm_status || batch.status || "").toLowerCase().includes("confirmed");
    const queueKey = this.erpWritebackQueueKey(batch);
    if (queueKey === "success") return { label: "推送成功", note: "ERP 已返回成功", className: "is-ok" };
    if (queueKey === "failed") return { label: "推送失败", note: "可查看原因后重试", className: "is-warn" };
    if (queueKey === "pending") return { label: "已生成报文", note: "等待正式接口推送", className: "is-info" };
    if (confirmed) return { label: "已校验", note: "可生成 ERP 报文", className: "is-ok" };
    if (statusInfo.needsRecalculate) return { label: "待重算", note: "先重新试算", className: "is-warn" };
    if (this.isPositive(totalCost)) return { label: "已试算", note: "等待人工校验", className: "is-info" };
    return { label: "待试算", note: itemCount ? "先补齐费用并试算" : "先导入物料", className: "is-muted" };
  }

  parentTableLabels() {
    const mode = this.normalizeTransportMode(this.filters.transport_mode);
    const role = this.workRoleInfo();
    const defaults = {
      title: role.title,
      logisticsNo: "批次/物流单号",
      blockName: role.blockName,
    };
    const byMode = {
      SEA: {
        title: "海运批次列表",
        logisticsNo: "批次/柜号",
        blockName: "海运单块",
      },
      AIR: {
        title: "空运批次列表",
        logisticsNo: "批次/空运单号",
        blockName: "空运单块",
      },
      EXPRESS: {
        title: "快递批次列表",
        logisticsNo: "批次/快递单号",
        blockName: "快递单块",
      },
    };
    return byMode[mode] || defaults;
  }

  batchListLabel(batch = {}, firstItem = {}) {
    return (
      batch.waybill_no ||
      firstItem.waybill_no ||
      batch.customs_no ||
      firstItem.customs_no ||
      batch.batch_no ||
      firstItem.batch_no ||
      batch.source_approval_no ||
      firstItem.source_approval_no ||
      batch.name ||
      "--"
    );
  }

  renderBatchRows(batch) {
    const isExpanded = this.expandedBatchNames.has(batch.name);
    return this.renderParentRow(batch, isExpanded) + (isExpanded ? this.renderChildRow(batch) : "");
  }

  renderParentRow(batch, isExpanded) {
    const items = this.batchItems[batch.name] || [];
    const hasLoadedItems = Object.prototype.hasOwnProperty.call(this.batchItems, batch.name);
    const firstItem = items[0] || {};
    const waybillNo = this.batchListLabel(batch, firstItem);
    const itemCount = hasLoadedItems ? items.length : batch.item_count || 0;
    const statusInfo = this.batchStatusInfo(batch.status, batch, itemCount);
    const documentStatus = this.batchDataCompleteness(batch, items, hasLoadedItems);
    const goodsValueDisplay = this.batchGoodsValueDisplay(batch, items, hasLoadedItems);
    const recognizedFeeDisplay = this.batchRecognizedFeeDisplay(batch, items, hasLoadedItems);
    const totalCostDisplay = this.batchTotalCostDisplay(batch, items, hasLoadedItems);
    const voucherDiffDisplay = this.batchVoucherDiffDisplay(batch);
    const importedClass = this.lastImportedBatchNames.has(batch.name) ? "imported" : "";
    const submittedAt = this.formatDateTimeMinute(batch.source_created_at);
    const sampleBadge = batch.is_classic_sample
      ? `<span class="ocw-sample-badge">${this.escape(batch.sample_note || "历史样本")}</span>`
      : "";
    this.activeBatchName = this.activeBatchName || batch.name;
    return `
      <tr class="ocw-parent-row ${isExpanded ? "expanded" : ""} ${importedClass}" data-batch-name="${this.escape(batch.name)}" title="单击批次可选中并锁定；双击打开详情侧边栏；字段修改请在明细区点击可编辑字段">
        <td>
          <button class="ocw-tree-toggle" data-action="toggle-batch" data-batch-name="${this.escape(batch.name)}" aria-expanded="${isExpanded ? "true" : "false"}">
            ${isExpanded ? "-" : "+"}
          </button>
        </td>
        <td title="${this.escape(this.formatValue(waybillNo || ""))}">
          <strong>${this.renderParentValue(waybillNo, "waybill_no")}</strong>
          <span class="ocw-batch-label-group">
            <span class="ocw-business-badge">${this.escape(this.businessTypeCompactLabel(batch.business_type || firstItem.business_type))}</span>
            <span class="ocw-status ${this.escape(this.statusClass(batch.status))}">${this.escape(statusInfo.label)}</span>
          </span>
          ${submittedAt ? `<small>提交时间 ${this.escape(submittedAt)}</small>` : ""}
          ${sampleBadge}
        </td>
        <td>${this.renderPurchaseApprovalMetric(batch.source_status || {})}</td>
        <td class="ocw-num-cell">${this.escape(String(itemCount))}</td>
        <td>${this.renderParentMetric(documentStatus)}</td>
        <td>${this.renderParentMetric(goodsValueDisplay)}</td>
        <td>${this.renderParentMetric(recognizedFeeDisplay)}</td>
        <td>${this.renderParentMetric(totalCostDisplay)}</td>
        <td>${this.renderParentMetric(voucherDiffDisplay)}</td>
        <td class="ocw-row-actions">
          <div class="ocw-row-action-group">
            ${this.workRole === "purchase"
              ? `<button class="ocw-outline-btn ocw-mini-btn" data-action="source-center" data-batch-name="${this.escape(batch.name)}">补资料</button>
                 <button class="ocw-outline-btn ocw-mini-btn" data-action="recalculate" data-batch-name="${this.escape(batch.name)}">试算</button>`
              : `<button class="ocw-outline-btn ocw-mini-btn" data-action="recalculate" data-batch-name="${this.escape(batch.name)}">重新试算</button>
                 <button class="ocw-outline-btn ocw-mini-btn" data-action="source-center" data-batch-name="${this.escape(batch.name)}">资料</button>`}
            <button class="ocw-outline-btn ocw-mini-btn" data-action="row-more" data-batch-name="${this.escape(batch.name)}">更多</button>
          </div>
        </td>
      </tr>
    `;
  }

  renderParentMetric(metric = {}) {
    const value = metric.value || "--";
    const hint = metric.hint ? `<small>${this.escape(metric.hint)}</small>` : "";
    return `
      <div class="ocw-parent-metric ${this.escape(metric.className || "muted")}">
        <strong>${this.escape(value)}</strong>
        ${hint}
      </div>
    `;
  }

  renderPurchaseApprovalMetric(sourceStatus = {}) {
    const state = String(sourceStatus.purchase_approval_sync_state || "").trim().toLowerCase();
    const count = Number(sourceStatus.linked_purchase_count || 0);
    const reason = sourceStatus.invalid_business_reason || sourceStatus.purchase_approval_sync_message || "";
    if (state === "invalid" || sourceStatus.invalid_business) {
      return `
        <div class="ocw-parent-metric ocw-purchase-approval-metric is-invalid" title="${this.escape(reason)}">
          <strong>采购审批无效</strong>
          <small>拒绝/撤销/终止</small>
        </div>
      `;
    }
    if (state === "pending") {
      return `
        <div class="ocw-parent-metric ocw-purchase-approval-metric is-pending" title="${this.escape(reason)}">
          <strong>状态未同步</strong>
          <small>${this.escape(`${count} 条已关联`)}</small>
        </div>
      `;
    }
    if (state === "missing" && sourceStatus.has_oa_logistics) {
      return `
        <div class="ocw-parent-metric ocw-purchase-approval-metric is-missing" title="${this.escape(reason)}">
          <strong>未关联</strong>
          <small>采购审批</small>
        </div>
      `;
    }
    if (state === "valid") {
      return `
        <div class="ocw-parent-metric ocw-purchase-approval-metric is-valid" title="${this.escape(reason)}">
          <strong>已关联</strong>
          <small>${this.escape(`${count} 条已同步`)}</small>
        </div>
      `;
    }
    return `<div class="ocw-parent-metric ocw-purchase-approval-metric is-muted"><strong>--</strong></div>`;
  }

  renderInvalidBusinessAlert(sourceStatus = {}) {
    const state = String(sourceStatus.purchase_approval_sync_state || "").trim().toLowerCase();
    if (!sourceStatus.invalid_business && state !== "invalid") return "";
    const reason = sourceStatus.invalid_business_reason || sourceStatus.purchase_approval_sync_message || "关联采购审批已拒绝/撤销/终止，不进入核算和 ERP 推送。";
    return `
      <div class="ocw-invalid-business-alert">
        <strong>采购审批无效</strong>
        <span>${this.escape(reason)}</span>
      </div>
    `;
  }

  renderPurchaseApprovalStatusAlert(sourceStatus = {}) {
    const state = String(sourceStatus.purchase_approval_sync_state || "").trim().toLowerCase();
    if (state === "invalid") return this.renderInvalidBusinessAlert(sourceStatus);
    if (state !== "pending" && state !== "missing") return "";
    const title = state === "pending" ? "采购审批状态未同步" : "未关联采购审批";
    return `
      <div class="ocw-invalid-business-alert is-info">
        <strong>${title}</strong>
        <span>${this.escape(sourceStatus.purchase_approval_sync_message || "采购审批状态尚未同步。")}</span>
      </div>
    `;
  }

  isInvalidApprovalStatusText(value) {
    const text = String(value || "").trim().toLowerCase();
    if (!text) return false;
    return [
      "rejected",
      "refused",
      "denied",
      "canceled",
      "cancelled",
      "terminated",
      "aborted",
      "revoked",
      "拒绝",
      "驳回",
      "已拒",
      "撤销",
      "取消",
      "终止",
      "作废",
      "不做",
    ].some((word) => text.includes(word.toLowerCase()));
  }

  batchDocumentStatus(batch, items, hasLoadedItems) {
    const sourceStatus = batch.source_status || {};
    if (sourceStatus.invalid_business) {
      return {
        value: "审批无效",
        hint: sourceStatus.invalid_business_reason || "已拒绝/撤销/终止",
        className: "danger",
      };
    }
    const itemCount = hasLoadedItems ? items.length : Number(batch.item_count || 0);
    const attachmentCount = Number(sourceStatus.oa_attachment_count || batch.source_attachment_count || 0);
    const packingListCount = Number(sourceStatus.packing_list_count || 0);
    const taxCertificateCount = Number(sourceStatus.tax_certificate_count || 0);
    const hasOaSource =
      Boolean(sourceStatus.has_oa_logistics) ||
      String(batch.source_type || "").trim() === "oa_logistics" ||
      this.hasText(batch.source_approval_no) ||
      this.hasText(batch.source_instance_id) ||
      this.hasText(batch.source_dingtalk_url);
    const parts = [];
    if (hasOaSource) parts.push("OA");
    if (attachmentCount) parts.push(`${attachmentCount}附件`);
    if (packingListCount) parts.push("装箱单");
    if (itemCount) parts.push(`${itemCount}SKU`);
    if (taxCertificateCount) parts.push("凭证");

    if (!parts.length) {
      return { value: "待资料", hint: "未关联 OA/附件", className: "warn" };
    }
    if (!itemCount) {
      return { value: "待解析", hint: parts.join(" / "), className: "warn" };
    }
    return {
      value: taxCertificateCount ? "资料较全" : "资料已读取",
      hint: parts.join(" / "),
      className: "ok",
    };
  }

  batchGoodsValueNumber(batch, items, hasLoadedItems) {
    const loadedValue = hasLoadedItems ? this.sumRowsNumber(items, "goods_value") : 0;
    const batchValue = Number(batch.total_goods_value || 0);
    return this.isPositive(loadedValue) ? loadedValue : batchValue;
  }

  batchTotalCostNumber(batch, items, hasLoadedItems) {
    const loadedValue = hasLoadedItems ? this.sumRowsNumber(items, "total_cost_rmb") : 0;
    const batchValue = Number(batch.actual_total_cost_rmb || batch.estimated_total_cost_rmb || 0);
    return this.isPositive(loadedValue) ? loadedValue : batchValue;
  }

  batchGoodsValueDisplay(batch, items, hasLoadedItems) {
    const itemCount = hasLoadedItems ? items.length : Number(batch.item_count || 0);
    const goodsValue = this.batchGoodsValueNumber(batch, items, hasLoadedItems);
    if (this.isPositive(goodsValue)) {
      return { value: `${this.formatNumber(goodsValue)} RMB`, hint: "来自采购/OA/明细", className: "ok" };
    }
    if (itemCount) {
      return { value: "待补采购金额", hint: "缺少采购单价或采购金额", className: "warn" };
    }
    return { value: "待物料", hint: "先生成 SKU", className: "muted" };
  }

  batchRecognizedFeeDisplay(batch, items, hasLoadedItems) {
    const itemCount = hasLoadedItems ? items.length : Number(batch.item_count || 0);
    const goodsValue = this.batchGoodsValueNumber(batch, items, hasLoadedItems);
    const totalCost = this.batchTotalCostNumber(batch, items, hasLoadedItems);
    const feeFromTotal = this.isPositive(totalCost) && totalCost > goodsValue ? totalCost - goodsValue : 0;
    const fallbackFeeFields = [
      "freight_alloc_rmb",
      "mexico_customs_rmb",
      "mexico_inland_misc_rmb",
      "china_misc_rmb",
      "china_to_mexico_freight_rmb",
    ];
    const fallbackFee = hasLoadedItems
      ? fallbackFeeFields.reduce((total, fieldname) => total + this.sumRowsNumber(items, fieldname), 0)
      : 0;
    const recognizedFee = this.isPositive(feeFromTotal) ? feeFromTotal : fallbackFee;
    if (this.isPositive(recognizedFee)) {
      return { value: `${this.formatNumber(recognizedFee)} RMB`, hint: "已计入试算", className: "ok" };
    }
    if (itemCount) {
      return { value: "待费用", hint: "等运费/税费/杂费", className: "warn" };
    }
    return { value: "--", hint: "暂无明细", className: "muted" };
  }

  batchTotalCostDisplay(batch, items, hasLoadedItems) {
    const itemCount = hasLoadedItems ? items.length : Number(batch.item_count || 0);
    const totalCost = this.batchTotalCostNumber(batch, items, hasLoadedItems);
    const statusInfo = this.batchStatusInfo(batch.status, batch, itemCount);
    if (statusInfo.needsRecalculate) {
      const hint = this.isPositive(totalCost) ? `当前 ${this.formatNumber(totalCost)} RMB` : "明细已修改";
      return { value: "待重算", hint, className: "warn" };
    }
    if (this.isPositive(totalCost)) {
      return { value: `${this.formatNumber(totalCost)} RMB`, hint: "已生成", className: "ok" };
    }
    if (itemCount) {
      return { value: "待试算", hint: "请先确认运费/税费/杂费", className: "warn" };
    }
    return { value: "待物料", hint: "暂无 SKU", className: "muted" };
  }

  batchVoucherDiffDisplay(batch) {
    const sourceStatus = batch.source_status || {};
    const reconciliation = sourceStatus.latest_tax_certificate_reconciliation || {};
    const taxCertificateCount = Number(sourceStatus.tax_certificate_count || 0);
    if (Object.keys(reconciliation).length) {
      const diff = Number(reconciliation.tax_total_diff_mxn);
      const statusLabel =
        reconciliation.manual_resolution_status_label || reconciliation.status_label || reconciliation.status || "已对账";
      if (Number.isFinite(diff)) {
        if (Math.abs(diff) <= 0.01) {
          return { value: "一致", hint: "0 MXN", className: "ok" };
        }
        return {
          value: statusLabel,
          hint: `${this.formatNumber(diff)} MXN`,
          className: "review",
        };
      }
      return {
        value: statusLabel,
        hint: reconciliation.file_name || "已登记凭证",
        className: String(statusLabel).includes("复核") ? "review" : "ok",
      };
    }
    if (taxCertificateCount) {
      return { value: "待对账", hint: `${taxCertificateCount} 份凭证`, className: "warn" };
    }
    return { value: "待凭证", hint: "最终对账", className: "muted" };
  }

  renderAllocationOverview(batch, items = []) {
    const rows = this.buildAllocationOverviewRows(batch, items);
    const sourcePrioritySummary = this.getSourcePrioritySummary(batch);
    const body = rows.length
      ? rows
          .map((row) => {
            const rowClass = row.className ? ` ${this.escape(row.className)}` : "";
            return `
              <div class="ocw-allocation-row${rowClass}">
                <div>
                  <strong>${this.escape(row.amountTitle)}</strong>
                  <span>${this.escape(row.amountText)}</span>
                </div>
                <div title="${this.escape(row.source)}">${this.escape(row.source)}</div>
                <div>${this.escape(row.basis)}</div>
                <div>${this.escape(row.result)}</div>
              </div>
            `;
          })
          .join("")
      : `
        <div class="ocw-allocation-empty">
          暂无可填入的费用分摊金额。请先确认物流费、清关费、税费或杂费，然后点击“重新试算”填入 AI/系统基础分摊金额。
        </div>
      `;

    return `
      <div class="ocw-allocation-overview">
        <div class="ocw-allocation-title">
          <div>
            <strong>AI/系统基础分摊填入</strong>
            <span>费用池金额 + 费用来源 + 分摊依据 + 分摊结果</span>
          </div>
          <button class="ocw-outline-btn ocw-mini-btn" type="button" data-action="manual-logistics-quote" data-batch-name="${this.escape(batch.name)}">物流报价/运费补录</button>
        </div>
        <div class="ocw-allocation-policy">
          <strong>当前口径</strong>
          <span>物流费、清关费、税费、仓储费、罚款、杂费等有来源的费用原则上都进综合成本；系统默认先按毛重分摊。确认属于抛货时，可人工改为体积/计费重后重新试算；${this.escape(sourcePrioritySummary)}</span>
        </div>
        <div class="ocw-allocation-grid">
          <div class="ocw-allocation-head">
            <span>费用池金额</span>
            <span>费用来源</span>
            <span>分摊依据</span>
            <span>分摊结果</span>
          </div>
          ${body}
        </div>
      </div>
    `;
  }

  buildAllocationOverviewRows(batch, items = []) {
    const buckets = new Map();
    items.forEach((item) => {
      const derived = this.parseJsonObject(item.derived_json);
      const rules = Array.isArray(derived.allocated_rules) ? derived.allocated_rules : [];
      rules.forEach((rule) => this.addAllocationRuleBucket(buckets, rule, item, batch));
    });

    const rows = Array.from(buckets.values()).map((bucket) => this.formatAllocationBucket(bucket));
    const customsRow = this.buildDirectCustomsAllocationRow(items);
    if (customsRow) rows.push(customsRow);
    const hasLogisticsRow = rows.some((row) => /物流|运输|运费|freight|logistics/i.test(`${row.amountTitle || ""} ${row.source || ""}`));
    const logisticsQuoteRow = hasLogisticsRow ? null : this.buildLogisticsQuoteAllocationRow(batch);
    if (logisticsQuoteRow) rows.unshift(logisticsQuoteRow);

    if (!rows.length) {
      const freightAlloc = this.sumRowsNumber(items, "freight_alloc_rmb");
      const freightAllocMxn = this.sumRowsNumber(items, "freight_alloc_mxn");
      const coveredRows = this.countRows(items, (row) => this.isPositive(row.freight_alloc_rmb) || this.isPositive(row.freight_alloc_mxn));
      if (this.isPositive(freightAlloc) || this.isPositive(freightAllocMxn)) {
        rows.push({
          amountTitle: "运输费用分摊",
          amountText: this.isPositive(freightAlloc)
            ? `${this.formatNumber(freightAlloc)} RMB`
            : `${this.formatNumber(freightAllocMxn)} MXN`,
          source: "历史试算结果",
          basis: "按已保存规则快照",
          result: `已分摊到 ${coveredRows || items.length} 行物料`,
        });
      }
    }

    return rows;
  }

  buildLogisticsQuoteAllocationRow(batch = {}) {
    const sourceStatus = batch.source_status || {};
    const confirmed = sourceStatus.confirmed_logistics_quote || {};
    const confirmedAmount = this.numericOrNull(confirmed.amount);
    if (this.isPositive(confirmedAmount)) {
      const carrier = String(confirmed.carrier || "").trim();
      const currency = this.normalizeCurrencyCode(confirmed.currency || "RMB");
      const basis = confirmed.allocation_basis || confirmed.basis || "gross_weight";
      return {
        amountTitle: "国际运输费用",
        amountText: `${carrier ? `${carrier} ` : ""}${this.formatNumber(confirmedAmount)} ${currency}`,
        source: "钉钉国际物流 OA/已确认报价",
        basis: this.allocationBasisLabel(basis),
        result: "已进入费用池，重新试算后分摊到物料",
        className: "is-confirmed",
      };
    }

    const candidates = Array.isArray(sourceStatus.logistics_quote_candidates) ? sourceStatus.logistics_quote_candidates : [];
    const validCandidates = candidates
      .map((candidate) => ({
        carrier: String(candidate.carrier || "").trim(),
        amount: this.numericOrNull(candidate.amount),
        currency: this.normalizeCurrencyCode(candidate.currency || "RMB"),
      }))
      .filter((candidate) => this.isPositive(candidate.amount));
    if (!validCandidates.length) return null;

    const sorted = validCandidates.slice().sort((a, b) => Number(a.amount || 0) - Number(b.amount || 0));
    const lowest = sorted[0];
    const lowestCount = sorted.filter(
      (candidate) => candidate.currency === lowest.currency && Math.abs(Number(candidate.amount || 0) - Number(lowest.amount || 0)) < 0.000001
    ).length;
    const carrierLabel = lowestCount > 1 ? `${lowestCount} 家最低` : lowest.carrier || "最低报价";
    return {
      amountTitle: "国际运输费用候选",
      amountText: `${carrierLabel} ${this.formatNumber(lowest.amount)} ${lowest.currency}；共 ${validCandidates.length} 份待确认`,
      source: "钉钉国际物流 OA 报价文本/附件",
      basis: "待人工确认后进入费用池",
      result: "确认报价并重新试算后分摊到物料",
      className: "is-pending",
    };
  }

  getSourcePrioritySummary(batch = {}) {
    const sourceStatus = batch.source_status || {};
    const summary = batch.summary_snapshot || {};
    const policy = sourceStatus.source_priority_policy || summary.source_priority_policy || {};
    return (
      sourceStatus.source_priority_summary ||
      policy.short_summary ||
      "税费听完税凭证；采购价听采购支出 OA；物流/清关/杂费听国际物流 OA；附件和 OCR 只做补充；人工调整保留记录。"
    );
  }

  addAllocationRuleBucket(buckets, rule = {}, item = {}, batch = {}) {
    const ruleCode = String(rule.rule_code || rule.fee_key || "").trim();
    const basis = String(rule.basis || rule.allocation_basis || rule.basis_label || "goods_value").trim();
    const currency = this.normalizeCurrencyCode(rule.currency || "RMB");
    const amount = this.numericOrNull(rule.amount);
    const amountKey = amount === null ? "allocated" : String(amount);
    const key = [ruleCode || "未命名费用", basis, currency, amountKey].join("|");
    const allocatedRmb = Number(this.numericOrNull(rule.allocated_rmb) || 0);
    const allocatedMxn = Number(this.numericOrNull(rule.allocated_mxn) || 0);
    if (!allocatedRmb && !allocatedMxn && amount === null) return;

    if (!buckets.has(key)) {
      buckets.set(key, {
        ruleCode,
        feeName: this.allocationFeeLabel(rule),
        basis,
        currency,
        amount,
        amountRmb: this.numericOrNull(rule.amount_rmb),
        source: this.allocationSourceLabel(rule, batch),
        allocatedRmb: 0,
        allocatedMxn: 0,
        coveredRows: new Set(),
      });
    }
    const bucket = buckets.get(key);
    bucket.allocatedRmb += allocatedRmb;
    bucket.allocatedMxn += allocatedMxn;
    if (item.name || item.row_no) bucket.coveredRows.add(item.name || item.row_no);
  }

  formatAllocationBucket(bucket) {
    let amountText = "--";
    if (bucket.amount !== null && bucket.amount !== undefined) {
      if (bucket.currency !== "RMB" && this.isPositive(bucket.amountRmb)) {
        amountText = `原币 ${this.formatNumber(bucket.amount)} ${bucket.currency || "RMB"}，折合 ${this.formatNumber(bucket.amountRmb)} RMB`;
      } else {
        amountText = `${this.formatNumber(bucket.amount)} ${bucket.currency || "RMB"}`;
      }
    } else if (this.isPositive(bucket.allocatedRmb)) {
      amountText = `${this.formatNumber(bucket.allocatedRmb)} RMB（按分摊汇总）`;
    } else if (this.isPositive(bucket.allocatedMxn)) {
      amountText = `${this.formatNumber(bucket.allocatedMxn)} MXN（按分摊汇总）`;
    }

    const resultParts = [];
    if (this.isPositive(bucket.allocatedRmb)) resultParts.push(`${this.formatNumber(bucket.allocatedRmb)} RMB`);
    if (this.isPositive(bucket.allocatedMxn)) resultParts.push(`${this.formatNumber(bucket.allocatedMxn)} MXN`);
    const coveredCount = bucket.coveredRows && bucket.coveredRows.size ? bucket.coveredRows.size : 0;
    if (coveredCount) resultParts.push(`覆盖 ${coveredCount} 行`);

    return {
      amountTitle: bucket.feeName || "费用池",
      amountText,
      source: bucket.source || "明细字段/系统规则",
      basis: this.allocationBasisLabel(bucket.basis),
      result: resultParts.length ? resultParts.join("，") : "待试算",
    };
  }

  buildDirectCustomsAllocationRow(items = []) {
    const customsRmb = this.sumRowsNumber(items, "mexico_customs_rmb");
    const customsMxn = this.sumRowsNumber(items, "mexico_customs_mxn");
    if (!this.isPositive(customsRmb) && !this.isPositive(customsMxn)) return null;
    const amountParts = [];
    if (this.isPositive(customsMxn)) amountParts.push(`${this.formatNumber(customsMxn)} MXN`);
    if (this.isPositive(customsRmb)) amountParts.push(`${this.formatNumber(customsRmb)} RMB`);
    const coveredRows = this.countRows(items, (row) => this.isPositive(row.mexico_customs_rmb) || this.isPositive(row.mexico_customs_mxn));
    return {
      amountTitle: "清关/税费",
      amountText: amountParts.join("，"),
      source: "完税凭证、清关资料或明细字段",
      basis: "已匹配到物料行",
      result: `计入 ${coveredRows || items.length} 行物料综合成本`,
    };
  }

  allocationFeeLabel(rule = {}) {
    const explicit = String(rule.expense_category || "").trim();
    const code = String(rule.rule_code || rule.fee_key || "").trim();
    const text = `${explicit} ${code}`.toLowerCase();
    if (text.includes("oa_logistics") || text.includes("freight") || text.includes("ocean") || text.includes("运费")) {
      return explicit && !explicit.toLowerCase().includes("freight") ? explicit : "国际运输费用";
    }
    if (code === "china_misc_rmb" || text.includes("china misc")) return "中国段杂费";
    if (code === "mexico_inland_misc_rmb" || text.includes("mexico inland")) return "墨西哥内陆/杂费";
    return explicit || code || "费用池";
  }

  allocationSourceLabel(rule = {}, batch = {}) {
    const remark = String(rule.remark || "").trim();
    const code = String(rule.rule_code || rule.fee_key || "").toLowerCase();
    const sourceStatus = batch.source_status || {};
    if (remark.includes("AI") || rule.is_ai_suggestion) return "AI基础分摊/待人工复核";
    if (remark.includes("钉钉") || code.includes("oa_logistics")) return "钉钉国际物流 OA";
    if ((sourceStatus.confirmed_logistics_quote || {}).amount && (code.includes("freight") || code.includes("logistics"))) {
      return "钉钉国际物流 OA/已确认物流报价";
    }
    if (remark.includes("货代") || code.includes("freight") || code.includes("ocean")) return "国际物流 OA/货代账单";
    if (remark.includes("清关") || remark.includes("墨西哥")) return "清关资料/墨西哥费用资料";
    if (remark.includes("Excel") || remark.includes("明细字段")) return "Excel/OA 明细字段";
    return "明细字段/系统规则";
  }

  allocationBasisLabel(value = "") {
    const basis = String(value || "").trim();
    const labels = {
      goods_value: "按货值比例分摊",
      gross_weight: "按毛重比例分摊",
      volume: "按体积比例分摊",
      chargeable_weight: "按计费重比例分摊",
      chargeable_weight_kg: "按计费重比例分摊",
    };
    return labels[basis] || (basis ? `按 ${basis} 分摊` : "按规则分摊");
  }

  renderChildRow(batch) {
    const items = this.batchItems[batch.name] || [];
    return `
      <tr class="ocw-child-row">
        <td colspan="11">
          <div class="ocw-child-table-shell">
            <div class="ocw-child-table-toolbar">
              <span>SKU 成本分摊明细 / 物料详情 · ${items.length} 行</span>
              <button class="ocw-outline-btn ocw-mini-btn ocw-add-material-sticky" data-action="add-material" data-batch-name="${this.escape(batch.name)}">+ 添加新物料</button>
            </div>
            ${this.renderAllocationOverview(batch, items)}
            ${this.renderChildTable(batch)}
            <div class="ocw-child-table-x-scroll" data-role="child-table-x-scroll" data-batch-name="${this.escape(batch.name)}" aria-label="SKU 明细横向滚动条">
              <div class="ocw-child-table-x-scroll-spacer" data-role="child-table-x-scroll-spacer"></div>
            </div>
          </div>
        </td>
      </tr>
    `;
  }

  renderChildTable(batch) {
    const columns = this.getChildDisplayColumns(this.batchColumns || []);
    const items = this.batchItems[batch.name] || [];
    if (!columns.length || !items.length) {
      return `<div class="ocw-muted">该报关/运单块暂无 SKU 明细</div>`;
    }
    const colgroup = columns
      .map((column, index) => `<col class="${this.escape(this.columnWidthClass(column, index))}" />`)
      .join("");
    const head = columns
      .map((column, index) => {
        const sticky = index < 2 ? `ocw-sticky-head ocw-sticky-${index}` : "";
        return `
          <th class="${sticky} ${this.escape(this.columnAlignClass(column))} notranslate" translate="no" title="${this.escape(column.excel_col + " " + column.label)}">
            ${this.renderHeaderCell(column)}
          </th>
        `;
      })
      .join("");
    const body = items
      .map((row) => {
        const cells = columns
          .map((column, index) => {
            const sticky = index < 2 ? `ocw-sticky-cell ocw-sticky-${index}` : "";
            const editable = this.isEditableColumn(column);
            const rawValue = this.shouldShowEmptyZeroFee(column.fieldname, row[column.fieldname])
              ? ""
              : this.normalizeEditorValue(row[column.fieldname]);
            const displayValue = this.formatCellValue(row[column.fieldname], column);
            return `
              <td
                class="${sticky} ${this.escape(this.columnAlignClass(column))} ${editable ? "ocw-editable-cell" : "ocw-readonly-cell"}"
                title="${this.escape(displayValue || "")}"
                data-editable-cell="${editable ? "1" : "0"}"
                data-batch-name="${this.escape(batch.name)}"
                data-item-name="${this.escape(row.name || "")}"
                data-version-name="${this.escape(row.version || batch.current_version || "")}"
                data-fieldname="${this.escape(column.fieldname)}"
                data-field-label="${this.escape(column.label)}"
                data-raw-value="${this.escape(rawValue)}"
                data-special-override="${this.specialOverrideFields.has(column.fieldname) ? "1" : "0"}"
              >
                ${this.renderCell(row[column.fieldname], column)}
              </td>
            `;
          })
          .join("");
        const itemLabel = row.product_name || row.material_code || row.name || "未命名物料";
        return `
          <tr>
            ${cells}
            <td class="ocw-row-action-cell">
              <button
                class="ocw-danger-btn ocw-mini-btn"
                data-action="delete-material"
                data-batch-name="${this.escape(batch.name)}"
                data-item-name="${this.escape(row.name || "")}"
                data-item-label="${this.escape(itemLabel)}"
              >删除</button>
            </td>
          </tr>
        `;
      })
      .join("");

    return `
      <div class="ocw-child-table-head-scroll" data-role="child-table-head-scroll" data-batch-name="${this.escape(batch.name)}">
        <table class="ocw-child-sku-table ocw-child-sku-head-table notranslate" translate="no">
          <colgroup>${colgroup}<col class="ocw-col-row-action" /></colgroup>
          <thead><tr>${head}<th class="ocw-row-action-head">操作</th></tr></thead>
        </table>
      </div>
      <div class="ocw-child-table-scroll" data-role="child-table-scroll" data-batch-name="${this.escape(batch.name)}">
        <table class="ocw-child-sku-table notranslate" translate="no">
          <colgroup>${colgroup}<col class="ocw-col-row-action" /></colgroup>
          <tbody>${body}</tbody>
        </table>
      </div>
    `;
  }

  renderHeaderCell(column) {
    const parts = this.splitHeaderLabel(column.label);
    const secondary = parts.secondary ? `<span class="ocw-sku-header-secondary">${this.escape(parts.secondary)}</span>` : "";
    return `
      <div class="ocw-sku-header-cell notranslate" translate="no">
        <span class="ocw-sku-header-code notranslate" translate="no">${this.escape(column.excel_col)}</span>
        <span class="ocw-sku-header-primary notranslate" translate="no">${this.escape(parts.primary)}</span>
        ${secondary}
      </div>
    `;
  }

  renderCell(value, column) {
    if (value === null || value === undefined || value === "" || this.shouldShowEmptyZeroFee(column.fieldname, value)) {
      return `<span class="ocw-table-display ocw-table-empty-value">--</span>`;
    }
    const formatted = this.formatCellValue(value, column);
    const highlighted = this.highlightText(formatted, this.filterTermsForColumn(column.fieldname));
    return `<span class="ocw-table-display">${highlighted}</span>`;
  }

  renderParentValue(value, fieldname) {
    return this.highlightText(this.formatValue(value || "--"), this.filterTermsForColumn(fieldname));
  }

  bindHierarchyScrollbars() {
    const bindPair = ($source, $bar) => {
      if (!$source.length || !$bar.length) return;
      const source = $source.get(0);
      const bar = $bar.get(0);
      const $spacer = $bar.find("[data-role$='scroll-spacer']");
      const $header = $source.prev("[data-role='child-table-head-scroll']");
      const syncHeader = () => {
        if ($header.length) $header.get(0).scrollLeft = source.scrollLeft;
      };
      const update = () => {
        const width = source.scrollWidth || source.clientWidth;
        $spacer.css("width", `${width}px`);
        $bar.toggleClass("is-hidden", width <= source.clientWidth + 1);
        bar.scrollLeft = source.scrollLeft;
        syncHeader();
      };
      let syncing = false;
      $source.off("scroll.ocwStickyX").on("scroll.ocwStickyX", () => {
        if (syncing) return;
        syncing = true;
        bar.scrollLeft = source.scrollLeft;
        syncHeader();
        syncing = false;
      });
      $bar.off("scroll.ocwStickyX").on("scroll.ocwStickyX", () => {
        if (syncing) return;
        syncing = true;
        source.scrollLeft = bar.scrollLeft;
        syncHeader();
        syncing = false;
      });
      update();
      window.requestAnimationFrame(update);
      window.setTimeout(update, 80);
    };

    const $hierarchyWrap = this.$root.find("[data-area='table']");
    bindPair($hierarchyWrap, this.$root.find("[data-role='hierarchy-x-scroll']"));
    this.$root.find("[data-role='child-table-scroll']").each((_, element) => {
      const $source = $(element);
      bindPair($source, $source.next("[data-role='child-table-x-scroll']"));
    });
    this.positionChildScrollbars();
    $hierarchyWrap
      .off("scroll.ocwChildScrollbarPosition")
      .on("scroll.ocwChildScrollbarPosition", () => {
        window.requestAnimationFrame(() => this.positionChildScrollbars());
      });
    $(window)
      .off("resize.ocwHierarchyScrollbars")
      .on("resize.ocwHierarchyScrollbars", () => {
        window.requestAnimationFrame(() => this.bindHierarchyScrollbars());
      });
  }

  positionChildScrollbars() {
    const $wrap = this.$root.find("[data-area='table']");
    if (!$wrap.length) return;
    const wrap = $wrap.get(0);
    const wrapRect = wrap.getBoundingClientRect();
    const hierarchyBarHeight = this.$root.find("[data-role='hierarchy-x-scroll']").not(".is-hidden").outerHeight() || 0;
    const visibleTop = wrapRect.top;
    const visibleBottom = wrapRect.bottom - hierarchyBarHeight;

    this.$root.find("[data-role='child-table-x-scroll']").each((_, barElement) => {
      const $bar = $(barElement);
      const $shell = $bar.closest(".ocw-child-table-shell");
      const $source = $bar.prev("[data-role='child-table-scroll']");
      if (!$shell.length || !$source.length) {
        $bar.addClass("is-hidden");
        return;
      }
      const shell = $shell.get(0);
      const source = $source.get(0);
      const shellRect = shell.getBoundingClientRect();
      const visibleHeight = Math.min(shellRect.bottom, visibleBottom) - Math.max(shellRect.top, visibleTop);
      const hasHorizontalScroll = source.scrollWidth > source.clientWidth + 1;
      if (!hasHorizontalScroll || visibleHeight < 64) {
        $bar.addClass("is-hidden");
        return;
      }
      const barHeight = barElement.offsetHeight || 18;
      const maxTop = Math.max(0, shell.offsetHeight - barHeight);
      const nextTop = Math.max(0, Math.min(visibleBottom - shellRect.top - barHeight, maxTop));
      barElement.style.top = `${nextTop}px`;
      $bar.removeClass("is-hidden");
    });
  }

  async exportCurrentResult() {
    const { batches, label } = this.getExportCurrentBatches();
    if (!batches.length) {
      frappe.msgprint("当前没有可导出的批次。");
      return;
    }
    const result = await this.call(
      "overseas_costing.api.batch.export_current_result_xlsx",
      {
        batch_names_json: JSON.stringify(batches.map((batch) => batch.name)),
        transport_label: label,
      },
      true
    );
    if (!result.ok) throw new Error(result.message || "导出失败");
    this.downloadBase64File(result.content_base64, result.file_name, result.mime_type);
    this.recordUsage("EXPORT", { remark: `导出当前全部批次结果：${label || "全部"}，${result.total || 0} 行`, extra: { total: result.total || 0 } });
    frappe.show_alert({ message: result.message || `已导出 ${result.total || 0} 行 SKU 明细。`, indicator: "green" });
  }

  async exportDrawerBatch() {
    const batch = this.drawerBatchName ? this.findBatch(this.drawerBatchName) : null;
    if (!batch) {
      frappe.msgprint("当前没有可导出的批次。");
      return;
    }
    const result = await this.call(
      "overseas_costing.api.batch.export_current_result_xlsx",
      {
        batch_names_json: JSON.stringify([batch.name]),
        transport_label: this.batchReferenceLabel(batch),
      },
      true
    );
    if (!result.ok) throw new Error(result.message || "导出失败");
    this.downloadBase64File(result.content_base64, result.file_name, result.mime_type);
    this.recordUsage("EXPORT", { batch, remark: `导出当前批次：${result.total || 0} 行`, extra: { total: result.total || 0 } });
    frappe.show_alert({ message: result.message || `已导出当前批次 ${result.total || 0} 行 SKU 明细。`, indicator: "green" });
  }

  async openBatchDrawer(batchName = "", options = {}) {
    const batch = batchName ? this.findBatch(batchName) : this.getActiveBatch();
    if (!batch) {
      this.showPendingFeature("当前没有可查看详情的批次。");
      return;
    }
    this.activeBatchName = batch.name;
    this.exportPinnedBatchName = batch.name;
    this.dataCheckBatchName = batch.name;
    this.drawerBatchName = batch.name;
    this.drawerTab = "overview";
    if (options.updateUrl !== false) {
      this.updateBatchUrl(this.batchUrlKey(batch), { view: "drawer" });
    }
    const $drawer = this.$root.find("[data-area='batch-drawer']");
    const $mask = this.$root.find("[data-area='batch-drawer-mask']");
    $drawer.attr("aria-hidden", "false").addClass("is-open");
    $mask.addClass("is-visible");
    this.renderBatchDrawerLoading();
    try {
      await this.loadBatchItems(batch.name, batch.current_version);
      await this.loadAuditLogs(batch.name, batch.current_version);
      this.recordUsage("BATCH_VIEW", { batch, remark: "打开批次详情抽屉" });
      this.renderBatchDrawer();
    } catch (error) {
      this.renderBatchDrawerError(error);
      this.showError(error);
    }
  }

  closeBatchDrawer(options = {}) {
    const $drawer = this.$root.find("[data-area='batch-drawer']");
    const $mask = this.$root.find("[data-area='batch-drawer-mask']");
    $drawer.attr("aria-hidden", "true").removeClass("is-open");
    $mask.removeClass("is-visible");
    if (options.updateUrl !== false) {
      const batch = this.findBatch(this.focusedBatchName) || this.findBatch(this.drawerBatchName);
      this.updateBatchUrl(this.batchUrlKey(batch), { view: "" });
    }
  }

  switchBatchDrawerTab(tab = "overview") {
    const allowedTabs = new Set(["overview", "items", "audit", "usage", "allocation"]);
    this.drawerTab = allowedTabs.has(tab) ? tab : "overview";
    if (this.drawerTab === "usage" && this.drawerBatchName) {
      this.loadUsageLogs(this.drawerBatchName).catch((error) => this.showError(error));
    }
    this.renderBatchDrawer();
  }

  renderBatchDrawerLoading() {
    this.$root.find("[data-area='batch-drawer-body']").html(`
      <div class="ocw-batch-drawer-loading">
        <span class="spinner-border spinner-border-sm"></span>
        <span>正在加载批次详情...</span>
      </div>
    `);
  }

  renderBatchDrawerError(error) {
    this.$root.find("[data-area='batch-drawer-body']").html(`
      <div class="ocw-batch-drawer-empty">
        <strong>批次详情加载失败</strong>
        <span>${this.escape(error && error.message ? error.message : "请刷新后重试")}</span>
      </div>
    `);
  }

  renderBatchDrawer() {
    const batch = this.findBatch(this.drawerBatchName);
    if (!batch) return;
    const items = this.batchItems[batch.name] || [];
    const $drawer = this.$root.find("[data-area='batch-drawer']");
    const title = batch.waybill_no || batch.customs_no || batch.batch_no || batch.name;
    $drawer.find("[data-area='batch-drawer-title']").text(title);
    $drawer.find("[data-action='switch-batch-drawer-tab']").each((_, node) => {
      $(node).toggleClass("active", $(node).attr("data-tab") === this.drawerTab);
    });
    $drawer.find("[data-area='batch-drawer-body']").html(this.renderBatchDrawerTab(batch, items));
  }

  renderBatchDrawerTab(batch, items) {
    if (this.drawerTab === "audit") {
      const auditHtml = this.auditEvents.length
        ? this.buildAuditSummaryEvents(this.auditEvents).map((event) => this.renderAuditEvent(event)).join("")
        : `<li class="ocw-audit-empty"><span class="ocw-audit-text">当前批次暂无修改记录</span></li>`;
      return `<ul class="ocw-audit-list ocw-batch-drawer-audit-list">${auditHtml}</ul>`;
    }
    if (this.drawerTab === "usage") {
      return this.renderUsageDrawer(batch);
    }
    if (this.drawerTab === "allocation") {
      return this.renderBatchDrawerAllocation(batch, items);
    }
    if (this.drawerTab === "profit") {
      return this.renderBatchDrawerProfit(batch, items);
    }
    if (this.drawerTab === "items") {
      return this.renderBatchDrawerItems(batch, items);
    }
    return this.renderBatchDrawerOverview(batch, items);
  }

  renderBatchDrawerOverview(batch, items) {
    const sourceStatus = batch.source_status || {};
    const logisticsTextSummary = sourceStatus.logistics_text_summary || {};
    const logisticsTextBrief = this.formatLogisticsTextSummary(logisticsTextSummary);
    const summary = batch.summary_snapshot || {};
    const itemCount = items.length || Number(batch.item_count || 0);
    const goodsValue = items.length ? this.sumRowsNumber(items, "goods_value") : Number(batch.total_goods_value || 0);
    const totalCost = items.length
      ? this.sumRowsNumber(items, "total_cost_rmb")
      : Number(batch.actual_total_cost_rmb || batch.estimated_total_cost_rmb || 0);
    const fields = [
      ["报关/来源单号", batch.customs_no || batch.source_approval_no || batch.batch_no || "--"],
      ["运单/柜号", batch.waybill_no || "--"],
      ["运输方式", this.transportLabel(batch.transport_mode)],
      ["业务类型", this.businessTypeLabel(batch.business_type)],
      ["状态", this.batchStatusInfo(batch.status, batch, itemCount).label],
      ["物料行数", itemCount],
      ["采购货值", `${this.formatNumber(goodsValue)} RMB`],
      ["综合成本", `${this.formatNumber(totalCost || summary.total_cost_rmb)} RMB`],
      ["采购审批", this.purchaseApprovalStatusLabel(sourceStatus)],
      ["资料情况", this.sourceStatusLabel(sourceStatus, batch)],
    ];
    const logisticsTextHtml = logisticsTextBrief
      ? `
        <div class="ocw-batch-drawer-note">
          <span>审批正文识别</span>
          <strong>${this.escape(logisticsTextBrief)}</strong>
        </div>
      `
      : "";
    const erpFlowHtml = this.renderErpFlowPanel(batch, items);
    return `
      <div class="ocw-batch-drawer-section ocw-batch-drawer-overview-brief">
        <div class="ocw-batch-drawer-field-grid">
          ${fields.map(([label, value]) => `<div><span>${this.escape(label)}</span><strong>${this.escape(this.formatValue(value))}</strong></div>`).join("")}
        </div>
        ${this.renderPurchaseApprovalStatusAlert(sourceStatus)}
        ${logisticsTextHtml}
      </div>
      ${erpFlowHtml}
    `;
  }

  renderBatchDrawerItems(batch, items) {
    const rows = (items || []).map((item, index) => `
      <tr>
        <td>${this.escape(String(index + 1))}</td>
        <td>${this.escape(this.formatValue(item.material_code || "--"))}</td>
        <td>${this.escape(this.formatValue(item.product_name || item.product_name_es || "--"))}</td>
        <td>${this.escape(this.formatValue(item.quantity))}</td>
        <td>${this.escape(this.formatValue(item.unit_price))}</td>
        <td>${this.escape(this.formatValue(item.purchase_currency || "--"))}</td>
        <td>${this.escape(this.formatValue(item.total_unit_rmb || "--"))}</td>
      </tr>
    `).join("");
    return `
      <div class="ocw-batch-drawer-section">
        <div class="ocw-batch-drawer-section-head"><h4>物料明细</h4><span>${items.length} 行，完整展示</span></div>
        ${rows ? `
          <div class="ocw-batch-drawer-table-wrap"><table class="ocw-batch-drawer-table"><thead><tr><th>#</th><th>物料编码</th><th>物料名称</th><th>采购数量</th><th>采购单价</th><th>采购币种</th><th>综合单价 RMB</th></tr></thead><tbody>${rows}</tbody></table></div>
        ` : `<div class="ocw-batch-drawer-empty"><span>当前批次暂无物料明细</span></div>`}
      </div>
    `;
  }

  formatProfitNumber(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return value === undefined || value === null ? "" : String(value);
    return number.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
  }

  profitDefaultFx(currency, item = {}) {
    const code = String(currency || item.sales_currency || "RMB").trim().toUpperCase();
    const saved = Number(item.sales_fx_rate);
    if (Number.isFinite(saved) && saved > 0) return saved;
    return code === "RMB" ? 1 : 0;
  }

  calculateProfitPreviewRow(item, values = {}) {
    const quantity = Number(values.sales_quantity ?? item.sales_quantity ?? 0) || 0;
    const unitPrice = Number(values.sales_unit_price ?? item.sales_unit_price ?? 0) || 0;
    const currency = String(values.sales_currency ?? item.sales_currency ?? "RMB").trim().toUpperCase() || "RMB";
    const fxRate = Number(values.sales_fx_rate ?? this.profitDefaultFx(currency, item)) || 0;
    const otherExpense = Number(values.other_sales_expense_rmb ?? item.other_sales_expense_rmb ?? 0) || 0;
    const costUnit = Number(item.total_unit_rmb) || 0;
    const salesAmount = quantity * unitPrice;
    const salesAmountRmb = salesAmount * fxRate;
    const salesCost = quantity * costUnit;
    const grossProfit = salesAmountRmb - salesCost;
    const profit = grossProfit - otherExpense;
    const margin = salesAmountRmb ? (profit / salesAmountRmb) * 100 : 0;
    const missing = [];
    if (quantity <= 0) missing.push("销售数量");
    if (unitPrice <= 0) missing.push("销售单价");
    if (fxRate <= 0) missing.push("销售汇率");
    if (costUnit <= 0) missing.push("综合成本单价");
    return {
      sales_quantity: quantity,
      sales_unit_price: unitPrice,
      sales_currency: currency,
      sales_fx_rate: fxRate,
      sales_amount: salesAmount,
      sales_amount_rmb: salesAmountRmb,
      sales_cost_rmb: salesCost,
      other_sales_expense_rmb: otherExpense,
      gross_profit_rmb: grossProfit,
      profit_rmb: profit,
      profit_margin: margin,
      profit_status: missing.length ? "PENDING" : "CALCULATED",
      profit_status_label: missing.length ? "待补销售数据" : "已测算",
      profit_missing_fields: missing,
    };
  }

  calculateProfitPreview(items, valuesByItem = {}) {
    const rows = (items || []).map((item) => this.calculateProfitPreviewRow(item, valuesByItem[item.name] || {}));
    const complete = rows.filter((row) => row.profit_status === "CALCULATED");
    const salesAmount = this.sumRowsNumber(complete, "sales_amount_rmb");
    const profit = this.sumRowsNumber(complete, "profit_rmb");
    return {
      item_count: rows.length,
      calculated_count: complete.length,
      pending_count: rows.length - complete.length,
      sales_amount_rmb: salesAmount,
      sales_cost_rmb: this.sumRowsNumber(complete, "sales_cost_rmb"),
      gross_profit_rmb: this.sumRowsNumber(complete, "gross_profit_rmb"),
      other_sales_expense_rmb: this.sumRowsNumber(complete, "other_sales_expense_rmb"),
      profit_rmb: profit,
      profit_margin: salesAmount ? (profit / salesAmount) * 100 : 0,
      rows,
    };
  }

  renderBatchDrawerProfit(batch, items, valuesByItem = {}) {
    const preview = this.calculateProfitPreview(items, valuesByItem);
    const summaryCards = [
      ["销售金额 RMB", preview.sales_amount_rmb],
      ["综合成本 RMB", preview.sales_cost_rmb],
      ["毛利 RMB", preview.gross_profit_rmb],
      ["其他销售费用 RMB", preview.other_sales_expense_rmb],
      ["利润 RMB", preview.profit_rmb],
      ["利润率", preview.calculated_count ? `${this.formatProfitNumber(preview.profit_margin)}%` : "--"],
    ]
      .map(([label, value]) => `<div class="ocw-profit-summary-card"><span>${label}</span><strong>${this.escape(typeof value === "number" ? this.formatProfitNumber(value) : value)}</strong></div>`)
      .join("");
    const rows = (items || []).map((item, index) => {
      const values = valuesByItem[item.name] || {};
      const row = this.calculateProfitPreviewRow(item, values);
      const savedCurrency = values.sales_currency ?? item.sales_currency ?? "RMB";
      const savedFx = values.sales_fx_rate ?? item.sales_fx_rate ?? (savedCurrency === "RMB" ? 1 : "");
      const input = (field, value) => `<input class="ocw-profit-input" data-profit-input="${field}" type="number" value="${this.escape(value === null || value === undefined ? "" : String(value))}" />`;
      return `
        <tr data-profit-row data-item-name="${this.escape(item.name || "")}">
          <td>${this.escape(String(index + 1))}</td>
          <td><strong>${this.escape(item.material_code || "--")}</strong><small>${this.escape(item.product_name || item.product_name_es || "")}</small></td>
          <td>${input("sales_quantity", values.sales_quantity ?? item.sales_quantity ?? "")}</td>
          <td>${input("sales_unit_price", values.sales_unit_price ?? item.sales_unit_price ?? "")}</td>
          <td><select class="ocw-profit-input" data-profit-input="sales_currency"><option value="RMB"${savedCurrency === "RMB" ? " selected" : ""}>RMB</option><option value="USD"${savedCurrency === "USD" ? " selected" : ""}>USD</option><option value="MXN"${savedCurrency === "MXN" ? " selected" : ""}>MXN</option></select></td>
          <td>${input("sales_fx_rate", savedFx)}</td>
          <td>${input("other_sales_expense_rmb", values.other_sales_expense_rmb ?? item.other_sales_expense_rmb ?? "")}</td>
          <td data-profit-result="sales_amount_rmb">${row.profit_status === "CALCULATED" ? this.formatProfitNumber(row.sales_amount_rmb) : "--"}</td>
          <td data-profit-result="sales_cost_rmb">${row.profit_status === "CALCULATED" ? this.formatProfitNumber(row.sales_cost_rmb) : "--"}</td>
          <td data-profit-result="gross_profit_rmb">${row.profit_status === "CALCULATED" ? this.formatProfitNumber(row.gross_profit_rmb) : "--"}</td>
          <td data-profit-result="profit_rmb">${row.profit_status === "CALCULATED" ? this.formatProfitNumber(row.profit_rmb) : "--"}</td>
          <td data-profit-result="profit_margin">${row.profit_status === "CALCULATED" ? `${this.formatProfitNumber(row.profit_margin)}%` : "--"}</td>
          <td data-profit-result="profit_status" class="${row.profit_status === "CALCULATED" ? "is-ok" : "is-pending"}">${row.profit_status_label}</td>
        </tr>
      `;
    }).join("");
    return `
      <div class="ocw-batch-drawer-section ocw-profit-panel">
        <div class="ocw-batch-drawer-section-head"><h4>利润测算</h4><span>销售数据人工录入，结果自动计算</span></div>
        <div class="ocw-profit-note">综合成本取当前批次的综合单价；物流、清关、关税等已包含在综合成本中的费用不会重复扣除。汇率填写“1销售币种 = 多少人民币”。</div>
        <div class="ocw-profit-summary">${summaryCards}</div>
        <div class="ocw-profit-status-line">已测算 ${preview.calculated_count} 行，待补销售数据 ${preview.pending_count} 行。汇总只统计已完成的明细。</div>
        <div class="ocw-batch-drawer-table-wrap ocw-profit-table-wrap">
          <table class="ocw-batch-drawer-table ocw-profit-table"><thead><tr><th>#</th><th>SKU</th><th>销售数量</th><th>销售单价</th><th>币种</th><th>汇率</th><th>其他销售费用 RMB</th><th>销售金额 RMB</th><th>综合成本 RMB</th><th>毛利 RMB</th><th>利润 RMB</th><th>利润率</th><th>状态</th></tr></thead><tbody>${rows || `<tr><td colspan="13">当前批次暂无物料明细</td></tr>`}</tbody></table>
        </div>
        <div class="ocw-profit-actions"><button class="ocw-primary-btn ocw-mini-btn" type="button" data-action="save-profit-inputs"${items.length ? "" : " disabled"}>保存并测算</button></div>
      </div>
    `;
  }

  readProfitDrawerValues() {
    const values = {};
    this.$root.find("[data-profit-row]").each((_, row) => {
      const $row = $(row);
      const itemName = $row.attr("data-item-name");
      if (!itemName) return;
      values[itemName] = {};
      $row.find("[data-profit-input]").each((__, input) => {
        values[itemName][$(input).attr("data-profit-input")] = $(input).val();
      });
    });
    return values;
  }

  updateProfitDrawerPreview() {
    if (this.drawerTab !== "profit") return;
    const batch = this.findBatch(this.drawerBatchName);
    if (!batch) return;
    const valuesByItem = this.readProfitDrawerValues();
    const preview = this.calculateProfitPreview(this.batchItems[batch.name] || [], valuesByItem);
    preview.rows.forEach((row, index) => {
      const $row = this.$root.find("[data-profit-row]").eq(index);
      ["sales_amount_rmb", "sales_cost_rmb", "gross_profit_rmb", "profit_rmb"].forEach((field) => {
        $row.find(`[data-profit-result="${field}"]`).text(row.profit_status === "CALCULATED" ? this.formatProfitNumber(row[field]) : "--");
      });
      $row.find('[data-profit-result="profit_margin"]').text(row.profit_status === "CALCULATED" ? `${this.formatProfitNumber(row.profit_margin)}%` : "--");
      $row.find('[data-profit-result="profit_status"]').text(row.profit_status_label).toggleClass("is-ok", row.profit_status === "CALCULATED").toggleClass("is-pending", row.profit_status !== "CALCULATED");
    });
    const $summary = this.$root.find(".ocw-profit-summary");
    const values = [preview.sales_amount_rmb, preview.sales_cost_rmb, preview.gross_profit_rmb, preview.other_sales_expense_rmb, preview.profit_rmb, preview.calculated_count ? `${this.formatProfitNumber(preview.profit_margin)}%` : "--"];
    $summary.find(".ocw-profit-summary-card strong").each((index, node) => $(node).text(typeof values[index] === "number" ? this.formatProfitNumber(values[index]) : values[index]));
    this.$root.find(".ocw-profit-status-line").text(`已测算 ${preview.calculated_count} 行，待补销售数据 ${preview.pending_count} 行。汇总只统计已完成的明细。`);
  }

  async saveProfitInputs() {
    const batch = this.findBatch(this.drawerBatchName);
    if (!batch) return;
    const valuesByItem = this.readProfitDrawerValues();
    const rows = Object.entries(valuesByItem).map(([item_name, values]) => ({ item_name, ...values }));
    const $button = this.$root.find("[data-action='save-profit-inputs']").prop("disabled", true).text("保存中");
    try {
      const result = await this.call("overseas_costing.api.profit.save_profit_inputs", {
        batch_name: batch.name,
        version_name: batch.current_version || null,
        rows_payload: JSON.stringify(rows),
      }, true);
      if (!result || !result.ok) throw new Error((result && result.message) || "利润测算保存失败");
      await this.loadBatchItems(batch.name, batch.current_version, true);
      await this.loadAuditLogs(batch.name, batch.current_version);
      this.renderTable();
      this.renderBatchDrawer();
      this.recordUsage("EDIT", { batch, remark: "保存利润测算销售数据" });
      frappe.show_alert({ message: result.message || "利润测算已保存", indicator: "green" });
    } catch (error) {
      this.showError(error);
      $button.prop("disabled", false).text("保存并测算");
    }
  }

  renderErpFlowPanel(batch, items) {
    const summary = batch.summary_snapshot || {};
    const itemCount = items.length || Number(batch.item_count || 0);
    const totalCost = items.length
      ? this.sumRowsNumber(items, "total_cost_rmb")
      : Number(batch.actual_total_cost_rmb || batch.estimated_total_cost_rmb || summary.total_cost_rmb || 0);
    const statusInfo = this.batchStatusInfo(batch.status, batch, itemCount);
    const hasVersion = this.hasText(batch.current_version);
    const confirmed = String(batch.confirm_status || batch.status || "").toLowerCase().includes("confirmed");
    const writebackInfo = this.erpWritebackStatusInfo(batch);
    const writebackLower = String(batch.writeback_status || "Not Started").toLowerCase();
    const invalidBusiness = Boolean((batch.source_status || {}).invalid_business);
    const canConfirm = hasVersion && !statusInfo.needsRecalculate && !invalidBusiness;
    const canPreview = confirmed && !invalidBusiness;
    const canPush = confirmed && !writebackLower.includes("success") && !invalidBusiness;
    const note = invalidBusiness
      ? "关联采购审批已拒绝、撤销或终止，当前批次保留用于追溯，但不会进入成本确认或 ERP 推送。"
      : confirmed
      ? "计算结果已通过人工校验，ERP 报文可预览后进入待推送队列。"
      : statusInfo.needsRecalculate
        ? "明细或费用池变更后需要重新试算，再进行人工校验。"
        : "核对费用池、分摊依据和明细结果后，执行人工校验。";
    const checkpoints = [
      { label: "综合成本", value: this.isPositive(totalCost) ? `${this.formatNumber(totalCost)} RMB` : "待试算", state: this.isPositive(totalCost) ? "is-ok" : "is-warn" },
      { label: "确认状态", value: confirmed ? "已确认" : "待确认", state: confirmed ? "is-ok" : "is-warn" },
      { label: "回写状态", value: writebackInfo.label, state: writebackInfo.state },
      { label: "业务主体", value: batch.subsidiary_code || "--", state: this.hasText(batch.subsidiary_code) ? "is-ok" : "is-warn" },
    ];
    const blockHtml = this.renderErpFlowBlockInline(batch);
    return `
      <div class="ocw-batch-drawer-section">
        <div class="ocw-erp-flow-panel">
          <div class="ocw-erp-flow-head">
            <h4>校验计算结果</h4>
            <span>${this.escape(statusInfo.label || "")}</span>
          </div>
          <div class="ocw-erp-flow-grid">
            ${checkpoints
              .map(
                (item) => `
                  <div class="${this.escape(item.state)}">
                    <span>${this.escape(item.label)}</span>
                    <strong>${this.escape(this.formatValue(item.value))}</strong>
                  </div>
                `
              )
              .join("")}
          </div>
          <div class="ocw-erp-flow-actions">
            <button class="ocw-primary-btn ocw-mini-btn" data-action="confirm-calculation-result"${canConfirm ? "" : " disabled"}>校验计算结果</button>
            <button class="ocw-outline-btn ocw-mini-btn" data-action="preview-erp-payload"${canPreview ? "" : " disabled"}>预览 ERP 报文</button>
            <button class="ocw-outline-btn ocw-mini-btn" data-action="writeback-to-erp"${canPush ? "" : " disabled"}>推送 ERP</button>
          </div>
          <div class="ocw-erp-flow-note">${this.escape(note)}</div>
        </div>
        ${blockHtml}
      </div>
    `;
  }

  renderBatchDrawerAllocation(batch, items) {
    const rows = this.buildAiReviewRows(batch, items);
    return `
      <div class="ocw-batch-drawer-section">
        <div class="ocw-batch-drawer-section-head"><h4>AI 分摊填入</h4><span>基础金额可在明细中人工调整</span></div>
        <div class="ocw-diff-table ocw-batch-drawer-diff-table">
          <div class="ocw-diff-head"><span>复核项</span><span>当前状态</span><span>说明</span></div>
          ${rows.map((row) => `<div><span>${this.escape(row.label)}</span><b class="${this.escape(row.statusClass)}">${this.escape(row.status)}</b><strong>${this.escape(row.suggestion)}</strong></div>`).join("")}
        </div>
      </div>
    `;
  }

  erpWritebackStatusInfo(batch = {}) {
    const writebackValue = String(batch.writeback_status || "Not Started");
    const writebackLower = writebackValue.toLowerCase();
    if (writebackLower.includes("success")) {
      return { label: "已完成", state: "is-ok", note: batch.writeback_message || "DeepLinkERP 已返回成功。" };
    }
    if (writebackLower.includes("pending")) {
      return { label: "待接口推送", state: "is-info", note: batch.writeback_message || "已生成报文，当前等待正式接口配置后推送。" };
    }
    if (writebackLower.includes("fail")) {
      return { label: "失败可重试", state: "is-warn", note: batch.writeback_message || "上次推送失败，后续可重试。" };
    }
    return { label: "未开始", state: "is-info", note: batch.writeback_message || "当前还没有生成 DeepLinkERP 待推送报文。" };
  }

  sourceStatusLabel(sourceStatus, batch) {
    if (sourceStatus.invalid_business) return "采购审批无效";
    if (Number(sourceStatus.oa_attachment_count || batch.source_attachment_count || 0) > 0) return "已有关联资料";
    if (batch.source_approval_no || batch.source_instance_id || batch.source_dingtalk_url) return "已关联钉钉审批单";
    return "待补资料";
  }

  purchaseApprovalStatusLabel(sourceStatus = {}) {
    const state = String(sourceStatus.purchase_approval_sync_state || "").trim().toLowerCase();
    const count = Number(sourceStatus.linked_purchase_count || 0);
    const statuses = Array.isArray(sourceStatus.linked_purchase_approval_statuses)
      ? sourceStatus.linked_purchase_approval_statuses.filter(Boolean)
      : [];
    if (state === "invalid" || sourceStatus.invalid_business) return "采购审批无效";
    if (state === "pending") return count ? `${count} 条状态未同步` : "状态未同步";
    if (state === "missing") return "未关联采购审批";
    if (state === "valid") return statuses.length ? `${count} 条：${statuses.join("/")}` : `${count} 条已同步`;
    return "--";
  }

  downloadBase64File(contentBase64, fileName, mimeType) {
    const binary = atob(contentBase64 || "");
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }
    const blob = new Blob([bytes], { type: mimeType || "application/octet-stream" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = fileName || "海外采购综合成本核算.xlsx";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }

  splitHeaderLabel(label) {
    const text = String(label || "");
    const match = text.match(/[A-Za-z][A-Za-z .()/%-]*/);
    if (!match || match.index === 0) return { primary: text, secondary: "" };
    return {
      primary: text.slice(0, match.index).trim(),
      secondary: text.slice(match.index).trim(),
    };
  }

  filterTermsForColumn(fieldname) {
    const value = this.filters[fieldname];
    return value ? [value] : [];
  }

  highlightText(value, terms) {
    let html = this.escape(value);
    terms
      .filter(Boolean)
      .map((term) => this.escapeRegExp(String(term)))
      .forEach((term) => {
        if (!term) return;
        html = html.replace(new RegExp(`(${term})`, "gi"), `<mark class="ocw-query-hit">$1</mark>`);
      });
    return html;
  }

  escapeRegExp(value) {
    return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  updateSearchResult() {
    const $result = this.$root.find("[data-area='search-result']");
    this.renderFilterChips();
    $result.removeClass("imported calculated");
    if (!this.hasActiveFilters()) {
      const role = this.workRoleInfo();
      $result.removeClass("active empty").text(`${role.label}视图：${role.description}；查询后会锁定当前结果，回到全部批次请点击“重置”`);
      return;
    }
    const modeLabel = this.filters.transport_mode ? `${this.transportLabel(this.filters.transport_mode)} · ` : "";
    if (this.visibleBatches.length) {
      $result
        .removeClass("empty")
        .addClass("active")
        .text(`${modeLabel}筛出 ${this.visibleBatches.length} 个报关/运单块 · 共 ${this.countVisibleItems()} 行 SKU（已自动展开）；当前结果已锁定，回到全部批次请点击“重置”`);
    } else {
      $result.removeClass("active").addClass("empty").text(`${modeLabel}未找到匹配的报关/运单块；回到全部批次请点击“重置”`);
    }
  }

  getExportCurrentBatches() {
    const pinnedBatch = this.exportPinnedBatchName ? this.findBatch(this.exportPinnedBatchName) : null;
    const pinnedInVisible = pinnedBatch && this.visibleBatches.some((batch) => batch.name === pinnedBatch.name);
    const mode = this.normalizeTransportMode(this.filters.transport_mode);
    const modeLabel = mode ? this.transportLabel(mode) : "全部";
    if (pinnedInVisible) {
      return {
        batches: [pinnedBatch],
        label: this.batchReferenceLabel(pinnedBatch),
      };
    }
    const batches = this.visibleBatches.length ? this.visibleBatches : this.getSelectableBatches();
    const label = batches.length === 1 ? this.batchReferenceLabel(batches[0]) : this.hasActiveFilters() ? `${modeLabel}筛选结果` : modeLabel;
    return { batches, label };
  }

  updateRecalculateAction() {
    if (!this.$root) return;
    const $buttons = this.$root.find("[data-action='recalculate']");
    if (!$buttons.length) return;

    $buttons.each((_, node) => {
      const $button = $(node);
      const batchName = $button.attr("data-batch-name");
      const batch = batchName ? this.findBatch(batchName) : this.getVisibleActiveBatch();

      $button.removeClass("needs-recalculate is-calculated").text("重新试算").attr("title", "");
      if (!batch) {
        $button.prop("disabled", true).attr("title", "暂无可试算批次");
        return;
      }

      const statusInfo = this.batchStatusInfo(batch.status);
      $button.prop("disabled", false).attr("title", "对当前批次重新计算分摊和综合成本");
      if (statusInfo.needsRecalculate) {
        $button.addClass("needs-recalculate").attr("title", statusInfo.suggestion);
        return;
      }

      if (String(batch.status || "").toLowerCase().includes("calculated")) {
        $button.addClass("is-calculated").attr("title", "当前批次已试算，可按需重新计算");
      }
    });
  }

  updateHierarchySummary() {
    if (this.erpQueueMode) {
      const stats = this.erpQueueStats();
      const statusText = this.erpQueueStatus === "all" ? "全部状态" : this.erpQueueStatusLabel(this.erpQueueStatus);
      this.$root
        .find("[data-area='hierarchy-summary']")
        .text(`ERP 队列 · ${statusText} ${this.getErpQueueBatches().length} 个批次 · 待推送 ${stats.pending || 0} 个`);
      return;
    }
    const displayBatches = this.getDisplayedBatches();
    const batchCount = displayBatches.length;
    const role = this.workRoleInfo();
    const modeLabel = this.filters.transport_mode ? `${this.transportLabel(this.filters.transport_mode)} · ` : "";
    const label = this.hasActiveFilters()
      ? `${role.label} · ${modeLabel}筛出 ${batchCount} 个报关/运单块 · 点击 + 展开 SKU 明细`
      : `${role.label} · ${batchCount} 个报关/运单块 · 点击 + 展开 SKU 明细`;
    this.$root.find("[data-area='hierarchy-summary']").text(label);
  }

  getDisplayedBatches() {
    if (this.focusedBatchName) {
      const focusedBatch = this.findBatch(this.focusedBatchName);
      return focusedBatch ? [focusedBatch] : [];
    }
    return this.visibleBatches;
  }

  renderBatchFocusControls() {
    const inFocusedView = Boolean(this.focusedBatchName);
    this.$root.find("[data-action='clear-batch-focus']").prop("hidden", !inFocusedView);
    this.$root.find("[data-action='expand-current'], [data-action='collapse-current']").prop("hidden", inFocusedView || this.erpQueueMode);
  }

  erpQueueStatusLabel(status = "all") {
    const labels = {
      all: "全部",
      not_started: "未开始",
      pending: "待推送",
      success: "成功",
      failed: "失败",
    };
    return labels[status] || status || "全部";
  }

  renderAuditList() {
    if (!this.auditEvents.length) {
      this.$root.find("[data-area='audit-list']").html(`
        <li class="ocw-audit-empty">
          <span class="ocw-audit-text">当前批次暂无修改记录</span>
        </li>
      `);
      return;
    }
    const displayEvents = this.buildAuditSummaryEvents(this.auditEvents);
    const html = displayEvents.map((event) => this.renderAuditEvent(event)).join("");
    this.$root.find("[data-area='audit-list']").html(html);
  }

  buildAuditSummaryEvents(events = []) {
    const orderedGroups = [];
    const groupMap = new Map();
    events.forEach((event) => {
      const key = this.auditSummaryKey(event);
      if (!key) {
        orderedGroups.push(event);
        return;
      }
      let group = groupMap.get(key);
      if (!group) {
        group = {
          summary: true,
          time: event.time || "",
          actor: event.actor || "",
          type: event.type || "",
          sourceLabel: this.auditSummarySourceLabel(event),
          added: 0,
          deleted: 0,
          modified: 0,
          uploaded: 0,
          actions: new Set(),
        };
        groupMap.set(key, group);
        orderedGroups.push(group);
      }
      this.collectAuditSummaryCount(group, event);
    });
    return orderedGroups.map((group) => (group.summary ? this.finalizeAuditSummaryEvent(group) : group));
  }

  auditSummaryKey(event) {
    if (!event || event.actionType === "RECALCULATE") return "";
    if (event.change) return "";
    if (!event.change && !["IMPORT", "EDIT", "BATCH_EDIT", "WRITEBACK", "UPLOAD_ATTACHMENT"].includes(event.actionType || "")) {
      return "";
    }
    const source = this.auditSummarySourceLabel(event);
    const remarkKey = this.normalizeAuditRemark(event.remark);
    return [event.type || "", event.actor || "", source, event.actionType || "", remarkKey].join("|");
  }

  auditSummarySourceLabel(event) {
    const remark = event.remark || "";
    const attachmentMatch = remark.match(/附件[:：]\s*([^；;，,\s]+)/);
    const fileMatch = remark.match(/(?:文件|资料)[:：]\s*([^；;，,\s]+)/);
    if (/采购支出/.test(remark)) return "采购支出 OA";
    if (/国际物流|钉钉|审批/.test(remark)) return "钉钉审批单";
    if (/补传资料|手动上传|人工上传/.test(remark)) return "补传资料";
    if (fileMatch && fileMatch[1]) return fileMatch[1];
    if (attachmentMatch && attachmentMatch[1]) return `附件 ${attachmentMatch[1]}`;
    return event.batchLabel || "当前表单";
  }

  normalizeAuditRemark(remark = "") {
    return String(remark || "")
      .replace(/附件[:：]\s*[^；;，,\s]+/g, "附件")
      .replace(/\s+/g, " ")
      .trim();
  }

  collectAuditSummaryCount(group, event) {
    if (event.change && event.fieldName === "item") {
      if (event.rawOldValue && !event.rawNewValue) {
        group.deleted += 1;
      } else if (!event.rawOldValue && event.rawNewValue) {
        group.added += 1;
      } else {
        group.modified += 1;
      }
      return;
    }
    if (event.change) {
      group.modified += 1;
      return;
    }
    if (event.actionType === "UPLOAD_ATTACHMENT") {
      group.uploaded += 1;
      return;
    }
    if (event.text || event.actionType) {
      group.actions.add(event.text || this.auditActionLabel(event.actionType));
    }
  }

  finalizeAuditSummaryEvent(group) {
    const pieces = [];
    if (group.added) pieces.push(`新增 ${group.added} 条物料`);
    if (group.deleted) pieces.push(`删除 ${group.deleted} 条物料`);
    if (group.modified) pieces.push(`修改 ${group.modified} 项字段`);
    if (group.uploaded) pieces.push(`上传 ${group.uploaded} 个附件`);
    if (!pieces.length && group.actions.size) pieces.push(Array.from(group.actions).join("，"));
    return {
      summary: true,
      time: group.time,
      actor: group.actor,
      type: group.type,
      sourceLabel: group.sourceLabel,
      text: pieces.length ? `${group.sourceLabel}：${pieces.join("，")}` : `${group.sourceLabel}：已处理`,
    };
  }

  mapAuditRow(row, batch) {
    const fieldName = row.field_name || "";
    const oldValue = row.old_value || "";
    const newValue = row.new_value || "";
    const hasChangeValue = oldValue !== "" || newValue !== "";
    const action = this.auditActionLabel(row.action_type, fieldName, oldValue, newValue);
    const field = this.auditFieldLabel(fieldName);
    const targetParts = [];
    if (row.row_no) targetParts.push(`第 ${row.row_no} 行`);
    if (batch && (batch.batch_no || batch.waybill_no)) targetParts.push(batch.batch_no || batch.waybill_no);
    const remark = row.action_remark || "";
    return {
      time: row.creation || "",
      actor: row.operator_name || (row.action_type === "EDIT" || row.action_type === "BATCH_EDIT" ? "人工" : "系统"),
      type: row.action_type === "EDIT" || row.action_type === "BATCH_EDIT" ? "manual" : "system",
      actionType: row.action_type || "",
      fieldName,
      rawOldValue: oldValue,
      rawNewValue: newValue,
      remark,
      batchLabel:
        (batch && (batch.source_title || batch.source_approval_no || batch.batch_no || batch.waybill_no || batch.customs_no || batch.name)) ||
        "",
      text: hasChangeValue ? "" : remark || action,
      change: hasChangeValue
        ? {
            action,
            field,
            target: targetParts.join(" · "),
            oldValue: this.formatAuditChangeValue(fieldName, oldValue),
            newValue: this.formatAuditChangeValue(fieldName, newValue),
          }
        : null,
    };
  }

  auditActionLabel(actionType, fieldName, oldValue, newValue) {
    if (fieldName === "item") {
      if (oldValue && !newValue) return "删除";
      if (!oldValue && newValue) return "新增";
    }
    if (fieldName === "erp_payload") return "生成待推送报文";
    if (fieldName === "confirm_status") return "校验通过";
    const labels = {
      IMPORT: "导入",
      EDIT: "修改",
      BATCH_EDIT: "修改",
      RECALCULATE: "重算",
      CREATE_VERSION: "创建版本",
      SWITCH_VERSION: "切换版本",
      UPLOAD_ATTACHMENT: "上传附件",
      WRITEBACK: "回写",
    };
    return labels[actionType] || actionType || "操作";
  }

  auditFieldLabel(fieldName) {
    if (!fieldName) return "";
    if (fieldName === "item") return "物料";
    if (fieldName === "allocation_rule") return "费用分摊规则";
    if (fieldName === "confirm_status") return "校验状态";
    if (fieldName === "erp_payload") return "ERP 报文";
    const column = (this.batchColumns || []).find((item) => item.fieldname === fieldName);
    return column ? column.label : fieldName;
  }

  formatAuditChangeValue(fieldName, value) {
    if (value === null || value === undefined || value === "") return "";
    const parsed = this.tryParseJson(value);
    if (fieldName === "allocation_rule") return this.formatAuditAllocationRule(parsed, value);
    if (fieldName === "confirm_status") return this.formatAuditConfirmStatus(parsed, value);
    if (fieldName === "erp_payload") return this.formatAuditErpPayload(parsed, value);
    if (fieldName !== "item") return this.formatAuditJsonValue(parsed, value);
    if (!parsed || typeof parsed !== "object") return value;
    const code = parsed.material_code || parsed.name || "";
    const name = parsed.product_name || "";
    const quantity = parsed.quantity !== undefined && parsed.quantity !== "" ? `，数量 ${parsed.quantity}` : "";
    const goodsValue = parsed.goods_value !== undefined && parsed.goods_value !== "" ? `，货值 ${parsed.goods_value}` : "";
    const label = [code, name].filter(Boolean).join(" / ");
    return `${label || "未命名物料"}${quantity}${goodsValue}`;
  }

  formatAuditAllocationRule(parsed, fallback) {
    if (!parsed || typeof parsed !== "object") return fallback;
    const category = parsed.expense_category || parsed.rule_code || "费用";
    const amount = parsed.amount !== undefined && parsed.amount !== "" ? this.formatNumber(parsed.amount) : "未填金额";
    const currency = parsed.currency || "";
    const basis = this.allocationBasisLabel(parsed.allocation_basis || parsed.basis);
    const source = parsed.source || "";
    const remark = parsed.remark || "";
    const pieces = [`${category}：${amount}${currency ? ` ${currency}` : ""}`];
    if (basis) pieces.push(`按${basis}分摊`);
    if (source) pieces.push(`来源 ${source}`);
    if (remark) pieces.push(remark);
    return pieces.join("，");
  }

  formatAuditConfirmStatus(parsed, fallback) {
    if (!parsed || typeof parsed !== "object") return fallback;
    const status = String(parsed.confirm_status || parsed.status || "").toLowerCase();
    const label = status.includes("confirmed") ? "已人工校验通过" : parsed.confirm_status || parsed.status || "已更新";
    return parsed.remark ? `${label}，备注：${parsed.remark}` : label;
  }

  formatAuditErpPayload(parsed, fallback) {
    if (!parsed || typeof parsed !== "object") return fallback;
    const target = parsed.target_system || "DeepLinkERP";
    const itemCount = parsed.item_count !== undefined ? `${parsed.item_count} 条物料` : "";
    const subsidiary = parsed.subsidiary_code ? `业务主体 ${parsed.subsidiary_code}` : "";
    return [`目标 ${target}`, subsidiary, itemCount].filter(Boolean).join("，");
  }

  formatAuditJsonValue(parsed, fallback) {
    if (!parsed || typeof parsed !== "object") return fallback;
    const entries = Object.entries(parsed)
      .filter(([, value]) => value !== null && value !== undefined && value !== "")
      .slice(0, 4)
      .map(([key, value]) => `${this.auditFieldLabel(key) || key} ${typeof value === "object" ? "已记录" : value}`);
    return entries.length ? entries.join("，") : fallback;
  }

  allocationBasisLabel(value) {
    const labels = {
      quantity: "数量",
      qty: "数量",
      gross_weight: "毛重",
      gross_weight_kg: "毛重",
      volume: "体积",
      volume_m3: "体积",
      goods_value: "货值",
      amount: "金额",
      equal: "平均",
    };
    return labels[value] || value || "";
  }

  mapUsageRow(row, batch) {
    const actor = row.operator_full_name || row.operator_name || "未知用户";
    const actionType = row.action_type || "OTHER";
    const actionLabel = this.usageActionLabel(actionType);
    const status = row.status || "Success";
    const batchLabel =
      (batch && (batch.source_title || batch.source_approval_no || batch.batch_no || batch.waybill_no || batch.customs_no || batch.name)) ||
      row.batch ||
      "";
    return {
      time: row.creation || "",
      actor,
      type: status === "Failed" ? "system" : "manual",
      actionType,
      status,
      text: `${actionLabel}${batchLabel ? ` · ${batchLabel}` : ""}${row.action_remark ? `：${row.action_remark}` : ""}`,
    };
  }

  usageActionLabel(actionType) {
    const labels = {
      PAGE_VIEW: "进入工作台",
      BATCH_VIEW: "查看批次",
      DINGTALK_PULL: "钉钉拉取",
      EXCEL_IMPORT: "Excel 导入",
      FILE_PARSE: "凭证对比",
      RECALCULATE: "重新试算",
      CONFIRM_RESULT: "校验结果",
      PREVIEW_ERP: "预览 ERP",
      PUSH_ERP: "推送 ERP",
      EXPORT: "导出",
      DATA_CHECK: "数据检查",
      ATTACHMENT_VIEW: "查看附件",
      OTHER: "其他操作",
    };
    return labels[actionType] || actionType || "操作";
  }

  renderUsageDrawer(batch = {}) {
    const summary = this.usageSummary || {};
    const users = summary.users || [];
    const actions = summary.actions || [];
    const writebackInfo = this.erpWritebackStatusInfo(batch);
    const userRows = users.length
      ? users
          .slice(0, 6)
          .map(
            (row) => `
              <div class="ocw-usage-chip">
                <strong>${this.escape(row.operator_full_name || row.operator_name || "未知用户")}</strong>
                <span>${this.escape(String(row.action_count || 0))} 次 · ${this.escape(row.last_seen || "--")}</span>
              </div>
            `
          )
          .join("")
      : `<div class="ocw-usage-empty">近 30 天暂无使用汇总</div>`;
    const actionRows = actions.length
      ? actions
          .slice(0, 6)
          .map(
            (row) => `
              <div class="ocw-usage-chip">
                <strong>${this.escape(this.usageActionLabel(row.action_type))}</strong>
                <span>${this.escape(String(row.action_count || 0))} 次</span>
              </div>
            `
          )
          .join("")
      : `<div class="ocw-usage-empty">暂无动作统计</div>`;
    const events = this.usageEvents.length
      ? this.usageEvents.map((event) => this.renderAuditEvent(event)).join("")
      : `<li class="ocw-audit-empty"><span class="ocw-audit-text">当前批次暂无使用记录</span></li>`;
    return `
      <div class="ocw-usage-panel">
        <div class="ocw-usage-status ${this.escape(writebackInfo.state)}">
          <div>
            <span>当前回写状态</span>
            <strong>${this.escape(writebackInfo.label)}</strong>
          </div>
          <p>${this.escape(writebackInfo.note)}</p>
        </div>
        <div class="ocw-usage-summary">
          <div>
            <h4>近 30 天活跃用户</h4>
            <div class="ocw-usage-chip-grid">${userRows}</div>
          </div>
          <div>
            <h4>近 30 天操作分布</h4>
            <div class="ocw-usage-chip-grid">${actionRows}</div>
          </div>
        </div>
        <ul class="ocw-audit-list ocw-batch-drawer-audit-list">${events}</ul>
      </div>
    `;
  }

  tryParseJson(value) {
    if (typeof value !== "string") return value;
    try {
      return JSON.parse(value);
    } catch (_error) {
      return null;
    }
  }

  renderAuditEvent(event) {
    const actor = `<b class="ocw-actor ${this.escape(event.type)}">${this.escape(event.actor)}</b>`;
    if (event.summary) {
      return `
        <li class="ocw-audit-summary-row">
          <span class="ocw-audit-time">${this.escape(event.time)}</span>
          ${actor}
          <span class="ocw-audit-text">${this.escape(event.text)}</span>
        </li>
      `;
    }
    if (!event.change) {
      return `
        <li>
          <span class="ocw-audit-time">${this.escape(event.time)}</span>
          ${actor}
          <span class="ocw-audit-text">${this.escape(event.text)}</span>
        </li>
      `;
    }

    const change = event.change;
    const title = [
      change.action || "修改",
      change.field ? `「${change.field}」` : "",
      change.target ? `· ${change.target}` : "",
    ]
      .filter(Boolean)
      .join(" ");
    const oldValue = this.escape(this.formatAuditValue(change.oldValue));
    const newValue = this.escape(this.formatAuditValue(change.newValue));
    return `
      <li class="ocw-audit-change-row">
        <span class="ocw-audit-time">${this.escape(event.time)}</span>
        ${actor}
        <div class="ocw-audit-change">
          <strong>${this.escape(title)}</strong>
          <div class="ocw-audit-values">
            <span>“${oldValue}”改成“${newValue}”</span>
          </div>
        </div>
      </li>
    `;
  }

  renderDiffPanel() {
    const batch = this.getDataCheckBatch();
    this.renderDataCheckBatchSelector(batch);
    if (!batch) {
      this.$root.find("[data-area='diff-panel']").html(`
        <div class="ocw-diff-table">
          <div class="ocw-diff-head"><span>复核项</span><span>当前状态</span><span>说明</span></div>
          <div><span>当前批次</span><b class="ocw-check-warn">未选择</b><strong>先选择一条批次查看 AI 分摊状态</strong></div>
        </div>
      `);
      return;
    }

    const items = this.batchItems[batch.name] || [];
    const rows = this.buildAiReviewRows(batch, items);
    const sourceStatus = batch.source_status || {};
    const batchLabel = batch.waybill_no || batch.customs_no || batch.batch_no || batch.name;
    const sourceNo = sourceStatus.source_no || batch.source_approval_no || batch.source_instance_id || "";
    const targetLabel =
      sourceNo && sourceNo !== batchLabel ? `${batchLabel || batch.name} / 来源 ${sourceNo}` : batchLabel || batch.name;
    const displayRows = [
      {
        label: "检查对象",
        status: "当前批次",
        statusClass: "ocw-check-info",
        suggestion: targetLabel,
      },
      {
        label: "取数优先级",
        status: "已确认",
        statusClass: "ocw-check-ok",
        suggestion: this.getSourcePrioritySummary(batch),
      },
      ...rows,
    ];
    this.$root.find("[data-area='diff-panel']").html(`
      <div class="ocw-diff-table">
        <div class="ocw-diff-head"><span>复核项</span><span>当前状态</span><span>说明</span></div>
        ${displayRows
          .map(
            (row) => `
              <div>
                <span>${this.escape(row.label)}</span>
                <b class="${this.escape(row.statusClass)}">${this.escape(row.status)}</b>
                <strong>${this.escape(row.suggestion)}</strong>
              </div>
            `
          )
          .join("")}
      </div>
    `);
  }

  buildAiReviewRows(batch, items = []) {
    const hasLoadedItems = Object.prototype.hasOwnProperty.call(this.batchItems, batch.name);
    const loadedItems = hasLoadedItems ? items : [];
    const itemCount = hasLoadedItems ? loadedItems.length : Number(batch.item_count || 0);
    const summary = batch.summary_snapshot || {};
    const ai = batch.ai_allocation || summary.ai_allocation || {};
    const ruleSnapshot = Array.isArray(batch.allocation_rule_snapshot) ? batch.allocation_rule_snapshot : [];
    const overviewRows = this.buildAllocationOverviewRows(batch, loadedItems);
    const positiveRules = ruleSnapshot.filter((rule) => this.isPositive(rule.amount) || this.isPositive(rule.amount_rmb));
    const aiRules = positiveRules.filter((rule) => rule.is_ai_suggestion || String(rule.remark || "").includes("AI"));
    const hasAi = Boolean(ai.ok || aiRules.length);
    const sourceStatus = batch.source_status || {};
    const confirmedQuote = sourceStatus.confirmed_logistics_quote || {};
    const freightValue =
      this.sumRowsNumber(loadedItems, "china_to_mexico_freight_rmb") ||
      this.sumRowsNumber(loadedItems, "china_ocean_usd") ||
      Number(confirmedQuote.amount || 0);
    const taxValue =
      this.sumRowsNumber(loadedItems, "import_tax_total") ||
      this.sumRowsNumber(loadedItems, "mexico_customs_mxn") ||
      this.sumRowsNumber(loadedItems, "mexico_customs_rmb");
    const miscValue =
      this.sumRowsNumber(loadedItems, "china_misc_rmb") ||
      this.sumRowsNumber(loadedItems, "mexico_inland_mxn") ||
      this.sumRowsNumber(loadedItems, "mexico_misc_mxn") ||
      this.sumRowsNumber(loadedItems, "mexico_inland_misc_rmb");
    const missingPrice = hasLoadedItems ? this.countRows(loadedItems, (row) => !this.isPositive(row.unit_price)) : 0;
    const missingGoods = hasLoadedItems ? this.countRows(loadedItems, (row) => !this.isPositive(row.goods_value)) : 0;
    const missingWeight = hasLoadedItems ? this.countRows(loadedItems, (row) => !this.isPositive(row.gross_weight_kg)) : 0;
    const missingCost = hasLoadedItems ? this.countRows(loadedItems, (row) => !this.isPositive(row.total_unit_rmb)) : 0;
    const feeHints = [];
    if (this.isPositive(freightValue)) feeHints.push("物流费");
    if (this.isPositive(taxValue)) feeHints.push("税费/清关费");
    if (this.isPositive(miscValue)) feeHints.push("杂费");
    const ruleBasisText = this.summarizeAllocationRuleBasis(positiveRules);
    const resultText = overviewRows.length
      ? overviewRows.slice(0, 2).map((row) => `${row.amountTitle}：${row.basis}，${row.result}`).join("；")
      : "暂无分摊结果，请先确认费用池并点击重新试算";
    const reviewIssues = [];
    if (missingPrice) reviewIssues.push(`单价缺 ${missingPrice} 行`);
    if (missingGoods) reviewIssues.push(`货值缺 ${missingGoods} 行`);
    if (missingWeight) reviewIssues.push(`毛重缺 ${missingWeight} 行`);
    if (missingCost) reviewIssues.push(`综合单价缺 ${missingCost} 行`);
    const calculationReview = summary.calculation_review || batch.calculation_review || {};
    const reviewReasons = Array.isArray(calculationReview.reasons)
      ? calculationReview.reasons.filter((reason) => this.hasText(reason))
      : [];
    const reviewStatus = calculationReview.status || "";
    const reviewLabel =
      calculationReview.label ||
      (!itemCount ? "待补数据" : reviewIssues.length || (!positiveRules.length && !overviewRows.length) ? "需人工复核" : "可先采用");
    const reviewStatusClass =
      reviewStatus === "usable" || reviewLabel === "可先采用"
        ? "ocw-check-ok"
        : reviewStatus === "blocked" || reviewLabel === "待补数据"
        ? "ocw-check-warn"
        : "ocw-check-info";
    const reviewSuggestion =
      calculationReview.reason ||
      reviewReasons.slice(0, 3).join("；") ||
      (reviewLabel === "可先采用"
        ? "核心采购金额、费用池和分摊结果已生成，可作为当前试算结果"
        : reviewIssues.length
        ? `${reviewIssues.join("，")}；请在明细区点击可编辑字段补齐后重新试算`
        : "先补齐物料、采购价格和费用池，再重新试算");

    return [
      {
        label: "核算结论",
        status: reviewLabel,
        statusClass: reviewStatusClass,
        suggestion: reviewSuggestion,
      },
      {
        label: "分摊填入",
        status: hasAi ? "AI已填" : positiveRules.length ? "系统已填" : "待费用",
        statusClass: hasAi ? "ocw-check-ok" : positiveRules.length ? "ocw-check-info" : "ocw-check-warn",
        suggestion: hasAi
          ? `AI 已选择基础分摊口径，系统已把分摊金额写入每行明细；模型 ${ai.model || "deepseek-v4-flash"}`
          : positiveRules.length
          ? ai.message || "当前使用系统基础规则，已按规则填入每行分摊金额"
          : "没有物流费、税费或杂费费用池时，AI 不会凭空生成费用分摊金额",
      },
      {
        label: "费用池",
        status: positiveRules.length ? `${positiveRules.length} 个` : feeHints.length ? `${feeHints.length} 类` : "0 个",
        statusClass: positiveRules.length || feeHints.length ? "ocw-check-ok" : "ocw-check-warn",
        suggestion: positiveRules.length
          ? this.summarizeAllocationRuleAmounts(positiveRules)
          : feeHints.length
          ? `已检测到${feeHints.join("、")}，点击重新试算后形成规则快照`
          : "先确认物流费、清关费、税费或杂费；否则只能填入货值/重量比例，费用分摊金额为 0",
      },
      {
        label: "分摊依据",
        status: ruleBasisText ? "已确定" : "待确定",
        statusClass: ruleBasisText ? "ocw-check-ok" : "ocw-check-warn",
        suggestion: ruleBasisText || "默认先按毛重分摊；抛货或特殊费用可人工改为体积/计费重后重新试算",
      },
      {
        label: "分摊结果",
        status: overviewRows.length ? `${overviewRows.length} 项` : itemCount ? "待重算" : "待物料",
        statusClass: overviewRows.length ? "ocw-check-ok" : "ocw-check-warn",
        suggestion: resultText,
      },
      {
        label: "人工调整",
        status: reviewIssues.length ? "需核对" : "可复核",
        statusClass: reviewIssues.length ? "ocw-check-warn" : "ocw-check-info",
        suggestion: reviewIssues.length
          ? `${reviewIssues.join("，")}；请在明细区点击可编辑字段补齐后重新试算`
          : "基础分摊金额已填入明细；如需人工调整，请在明细区点击可编辑字段，税费最终以完税凭证对账为准",
      },
    ];
  }

  summarizeAllocationRuleAmounts(rules = []) {
    return rules
      .slice(0, 3)
      .map((rule) => {
        const amount = this.numericOrNull(rule.amount);
        const currency = this.normalizeCurrencyCode(rule.currency || "RMB");
        return `${this.allocationFeeLabel(rule)} ${amount === null ? "--" : this.formatNumber(amount)} ${currency}`;
      })
      .join("；");
  }

  summarizeAllocationRuleBasis(rules = []) {
    if (!rules.length) return "";
    return rules
      .slice(0, 3)
      .map((rule) => `${this.allocationFeeLabel(rule)}：${this.allocationBasisLabel(rule.allocation_basis || rule.basis_field)}`)
      .join("；");
  }

  buildDataCheckRows(batch, items) {
    const hasLoadedItems = Object.prototype.hasOwnProperty.call(this.batchItems, batch.name);
    const loadedItems = hasLoadedItems ? items : [];
    const customsNo = batch.customs_no || this.firstLoadedValue(items, "customs_no");
    const waybillNo = batch.waybill_no || this.firstLoadedValue(items, "waybill_no");
    const sourceNo = batch.source_approval_no || batch.source_instance_id || batch.batch_no || this.firstLoadedValue(items, "source_doc_no");
    const itemCount = hasLoadedItems ? loadedItems.length : Number(batch.item_count || 0);
    const goodsValue = hasLoadedItems ? this.sumRowsNumber(loadedItems, "goods_value") : Number(batch.total_goods_value || 0);
    const grossWeight = hasLoadedItems ? this.sumRowsNumber(loadedItems, "gross_weight_kg") : Number(batch.total_gross_weight_kg || 0);
    const freightAlloc = hasLoadedItems ? this.sumRowsNumber(loadedItems, "freight_alloc_rmb") : 0;
    const totalCost = hasLoadedItems
      ? this.sumRowsNumber(loadedItems, "total_cost_rmb")
      : Number(batch.actual_total_cost_rmb || batch.estimated_total_cost_rmb || 0);
    const taxTotal = hasLoadedItems
      ? this.sumRowsNumber(loadedItems, "import_tax_total") ||
        this.sumRowsNumber(loadedItems, "mexico_customs_mxn") ||
        this.sumRowsNumber(loadedItems, "igi_amount") + this.sumRowsNumber(loadedItems, "iva_amount")
      : 0;
    const batchStatus = this.batchStatusInfo(batch.status, batch, itemCount);
    const sourceStatus = batch.source_status || {};

    const hasOaSource =
      Boolean(sourceStatus.has_oa_logistics) ||
      String(batch.source_type || "").trim() === "oa_logistics" ||
      this.hasText(batch.source_approval_no) ||
      this.hasText(batch.source_instance_id) ||
      this.hasText(batch.source_dingtalk_url) ||
      this.countRows(loadedItems, (row) => this.hasText(row.dingtalk_instance_id) || this.hasText(row.dingtalk_official_url)) > 0;
    const missingCode = hasLoadedItems ? this.countRows(loadedItems, (row) => !this.hasText(row.material_code)) : 0;
    const missingName = hasLoadedItems ? this.countRows(loadedItems, (row) => !this.hasText(row.product_name)) : 0;
    const badQuantity = hasLoadedItems ? this.countRows(loadedItems, (row) => !this.isPositive(row.quantity)) : 0;
    const badPrice = hasLoadedItems ? this.countRows(loadedItems, (row) => !this.isPositive(row.unit_price)) : 0;
    const badCurrency = hasLoadedItems ? this.countRows(loadedItems, (row) => !this.hasText(row.purchase_currency)) : 0;
    const badGoods = hasLoadedItems ? this.countRows(loadedItems, (row) => !this.isPositive(row.goods_value)) : 0;
    const badActualQty = hasLoadedItems ? this.countRows(loadedItems, (row) => !this.isPositive(row.actual_shipped_qty)) : 0;
    const badWeight = hasLoadedItems ? this.countRows(loadedItems, (row) => !this.isPositive(row.gross_weight_kg)) : 0;
    const rowsWithTax = hasLoadedItems
      ? this.countRows(
          loadedItems,
          (row) =>
            this.isPositive(row.import_tax_total) ||
            this.isPositive(row.mexico_customs_mxn) ||
            this.isPositive(row.igi_amount) ||
            this.isPositive(row.iva_amount)
        )
      : 0;
    const badUnitCost = hasLoadedItems ? this.countRows(loadedItems, (row) => !this.isPositive(row.total_unit_rmb)) : 0;
    const needsRecalculate = batchStatus.needsRecalculate || badUnitCost > 0;
    const missingMaterialDetail = this.describeProblemRows(
      loadedItems,
      (row) => !this.hasText(row.material_code) || !this.hasText(row.product_name) || !this.isPositive(row.quantity)
    );
    const missingPurchaseDetail = this.describeProblemRows(
      loadedItems,
      (row) => !this.isPositive(row.unit_price) || !this.hasText(row.purchase_currency) || !this.isPositive(row.goods_value)
    );
    const missingPackingDetail = this.describeProblemRows(
      loadedItems,
      (row) => !this.isPositive(row.actual_shipped_qty) || !this.isPositive(row.gross_weight_kg)
    );
    const missingCostDetail = this.describeProblemRows(loadedItems, (row) => !this.isPositive(row.total_unit_rmb));
    const attachmentCount = Number(sourceStatus.oa_attachment_count || batch.source_attachment_count || 0);
    const packingListCount = Number(sourceStatus.packing_list_count || 0);
    const taxCertificateCount = Number(sourceStatus.tax_certificate_count || 0);
    const parsedTaxCertificateCount = Number(sourceStatus.parsed_tax_certificate_count || 0);
    const quoteCandidateCount = Number(sourceStatus.logistics_quote_candidate_count || 0);
    const confirmedQuote = sourceStatus.confirmed_logistics_quote || {};
    const logisticsTextSummary = sourceStatus.logistics_text_summary || {};
    const logisticsTextBrief = this.formatLogisticsTextSummary(logisticsTextSummary);
    const sourceStatusNo = sourceStatus.source_no || sourceNo;
    const transportMode = this.normalizeTransportMode(batch.transport_mode || this.firstLoadedValue(loadedItems, "transport_mode"));
    const transportCopy = this.dataCheckTransportCopy(transportMode);

    return [
      {
        label: "核算状态",
        status: batchStatus.label,
        statusClass: batchStatus.statusClass,
        suggestion: batchStatus.suggestion,
      },
      {
        label: "国际物流 OA",
        status: hasOaSource ? "已关联" : "未关联",
        statusClass: hasOaSource ? "ocw-check-ok" : "ocw-check-warn",
        suggestion: hasOaSource ? `${sourceStatusNo || "--"}，可跳转原审批单` : "先从钉钉国际物流流程拉取或补审批链接",
      },
      {
        label: "物料明细",
        status: !itemCount ? "待生成" : !hasLoadedItems ? "待展开" : missingCode || missingName || badQuantity ? "需核对" : `${itemCount} 行`,
        statusClass: !itemCount || missingCode || missingName || badQuantity ? "ocw-check-warn" : "ocw-check-ok",
        suggestion: !itemCount
          ? "国际物流 OA 或附件解析后生成物料行"
          : !hasLoadedItems
          ? "展开批次后检查行级字段"
          : missingCode || missingName || badQuantity
          ? `编码缺 ${missingCode} 行，名称缺 ${missingName} 行，数量异常 ${badQuantity} 行；${missingMaterialDetail}`
          : `${customsNo || sourceNo || "--"} / ${waybillNo || "--"}`,
      },
      {
        label: "采购价格",
        status: !itemCount ? "待物料" : !hasLoadedItems ? "待展开" : badPrice || badCurrency || badGoods ? "待同步" : this.formatNumber(goodsValue),
        statusClass: !itemCount || badPrice || badCurrency || badGoods ? "ocw-check-warn" : "ocw-check-ok",
        suggestion: !itemCount
          ? "先有物料行，再从采购支出 OA 补价格"
          : !hasLoadedItems
          ? "展开批次后检查采购单价和币种"
          : badPrice || badCurrency || badGoods
          ? `单价缺 ${badPrice} 行，币种缺 ${badCurrency} 行，货值缺 ${badGoods} 行；${missingPurchaseDetail}`
          : "已具备单价、币种和总货值",
      },
      {
        label: "物流费用",
        status: this.isPositive(confirmedQuote.amount)
          ? `${this.formatNumber(confirmedQuote.amount)} ${confirmedQuote.currency || "RMB"}`
          : quoteCandidateCount
          ? `${quoteCandidateCount} 份待确认`
          : "待费用",
        statusClass: this.isPositive(confirmedQuote.amount) ? "ocw-check-ok" : "ocw-check-warn",
        suggestion: this.isPositive(confirmedQuote.amount)
          ? `${confirmedQuote.carrier || "已确认报价"}已参与整票物流费用分摊`
          : quoteCandidateCount
          ? "在相关资料中确认最终物流报价后再参与试算"
          : transportCopy.missingFreightSuggestion,
      },
      {
        label: "审批正文识别",
        status: logisticsTextBrief ? "已识别" : "待识别",
        statusClass: logisticsTextBrief ? "ocw-check-ok" : "ocw-check-warn",
        suggestion: logisticsTextBrief || "可从钉钉正文识别物流方式、报价、重量、预计发货日期和目的地",
      },
      {
        label: "发起附件",
        status: attachmentCount ? `${attachmentCount} 个` : "待拉取",
        statusClass: attachmentCount ? "ocw-check-ok" : "ocw-check-warn",
        suggestion: attachmentCount ? `资料里可查看${transportCopy.attachmentExamples}` : "从国际物流 OA 拉取发起人上传附件",
      },
      {
        label: transportCopy.packingLabel,
        status: !itemCount ? "待物料" : !hasLoadedItems ? "待展开" : badActualQty || badWeight ? "待补齐" : `${this.formatNumber(grossWeight)} KG`,
        statusClass: !itemCount || badActualQty || badWeight ? "ocw-check-warn" : "ocw-check-ok",
        suggestion: !itemCount
          ? "先生成物料行"
          : !hasLoadedItems
          ? "展开批次后检查实际数量和毛重"
          : packingListCount && (badActualQty || badWeight)
          ? `已登记装箱单 ${packingListCount} 个；实际数量缺 ${badActualQty} 行，毛重缺 ${badWeight} 行；${missingPackingDetail}`
          : badActualQty || badWeight
          ? `实际数量缺 ${badActualQty} 行，毛重缺 ${badWeight} 行；${missingPackingDetail}`
          : transportCopy.packingReadySuggestion,
      },
      {
        label: "税费凭证",
        status: taxCertificateCount ? `${taxCertificateCount} 份` : rowsWithTax ? `${rowsWithTax} 行` : "待凭证",
        statusClass: taxCertificateCount || rowsWithTax ? "ocw-check-ok" : "ocw-check-warn",
        suggestion: taxCertificateCount
          ? `已登记 ${taxCertificateCount} 份凭证${parsedTaxCertificateCount ? `，其中 ${parsedTaxCertificateCount} 份已有记录` : ""}，用于最终多退少补对账`
          : rowsWithTax
          ? `系统已有税费 ${this.formatNumber(taxTotal)} MXN，后续仍需凭证对账`
          : "完税凭证或清关资料补齐后再做最终对账",
      },
      {
        label: "试算结果",
        status: !itemCount ? "待物料" : needsRecalculate || !this.isPositive(totalCost) ? "待重算" : this.formatNumber(totalCost),
        statusClass: !itemCount || needsRecalculate || !this.isPositive(totalCost) ? "ocw-check-warn" : "ocw-check-ok",
        suggestion: !itemCount
          ? "先形成批次物料明细"
          : batchStatus.needsRecalculate
          ? "明细已修改，请点击重新试算"
          : badUnitCost
          ? `综合单价缺 ${badUnitCost} 行：${missingCostDetail}；点击重新试算`
          : `已生成综合成本，国际运费分摊 ${this.formatNumber(freightAlloc)} RMB`,
      },
    ];
  }

  dataCheckTransportCopy(mode = "") {
    const normalized = this.normalizeTransportMode(mode);
    const copies = {
      SEA: {
        attachmentExamples: "装箱单、提单、发票等原始附件",
        packingLabel: "装箱单数据",
        packingReadySuggestion: "可用于海运重量分摊，体积按后续口径复核",
        missingFreightSuggestion: "等待物流 OA 填写海运费，或补充货代账单/报价资料",
      },
      AIR: {
        attachmentExamples: "空运运单、装箱单、发票等原始附件",
        packingLabel: "空运基础数据",
        packingReadySuggestion: "已具备实际数量和毛重；空运按现有口径以发货数量计算平均成本",
        missingFreightSuggestion: "等待物流 OA 填写空运费，或补充空运账单/报价资料",
      },
      EXPRESS: {
        attachmentExamples: "快递面单、货品明细、发票/账单等原始附件",
        packingLabel: "快递基础数据",
        packingReadySuggestion: "已具备实际数量和重量；后续按快递账单或双清费用核对",
        missingFreightSuggestion: "等待物流 OA 填写快递/双清费用，或补充快递账单",
      },
    };
    return (
      copies[normalized] || {
        attachmentExamples: "装箱单、运单、发票等原始附件",
        packingLabel: "发货基础数据",
        packingReadySuggestion: "已具备实际数量和重量，可继续核对费用分摊",
        missingFreightSuggestion: "等待物流 OA 填写明确费用，或补充物流账单/报价资料",
      }
    );
  }

  addAudit(actor, type, textOrChange) {
    this.auditEvents.unshift({
      time: this.nowText(),
      actor,
      type,
      ...(typeof textOrChange === "object" && textOrChange !== null
        ? { text: textOrChange.text || "", change: textOrChange.change || textOrChange }
        : { text: textOrChange }),
    });
    this.renderAuditList();
  }

  async toggleBatch(batchName) {
    if (!batchName) return;
    this.activeBatchName = batchName;
    this.exportPinnedBatchName = batchName;
    this.dataCheckBatchName = batchName;
    if (this.expandedBatchNames.has(batchName)) {
      this.expandedBatchNames.delete(batchName);
    } else {
      const batch = this.findBatch(batchName);
      await this.loadBatchItems(batchName, batch ? batch.current_version : null);
      this.expandedBatchNames.add(batchName);
    }
    this.renderTable();
    this.renderDiffPanel();
  }

  async selectBatch(batchName) {
    if (!batchName) return;
    const batch = this.findBatch(batchName);
    if (!batch) return;
    this.activeBatchName = batch.name;
    this.exportPinnedBatchName = batch.name;
    this.dataCheckBatchName = batch.name;
    await this.loadAuditLogs(batch.name, batch.current_version);
    this.renderTable();
    this.renderDiffPanel();
    this.updateBatchUrl(this.batchUrlKey(batch), { view: "" });
  }

  async focusBatch(batchName, options = {}) {
    if (!batchName) return;
    const batch = this.findBatch(batchName);
    if (!batch) return;
    this.focusedBatchName = batch.name;
    this.activeBatchName = batch.name;
    this.exportPinnedBatchName = batch.name;
    this.dataCheckBatchName = batch.name;
    await Promise.all([
      this.loadBatchItems(batch.name, batch.current_version),
      this.loadAuditLogs(batch.name, batch.current_version),
    ]);
    this.expandedBatchNames.add(batch.name);
    this.renderTable();
    this.renderDiffPanel();
    if (options.updateUrl !== false) this.updateBatchUrl(this.batchUrlKey(batch), { view: "" });
  }

  clearBatchFocus(options = {}) {
    this.focusedBatchName = "";
    this.closeBatchDrawer({ updateUrl: false });
    this.renderTable();
    this.updateSearchResult();
    if (options.updateUrl !== false) this.updateBatchUrl("", { view: "" });
  }

  getBatchNameFromUrl() {
    try {
      return String(new URL(window.location.href).searchParams.get("batch") || "").trim();
    } catch (_error) {
      return "";
    }
  }

  getBatchViewFromUrl() {
    try {
      return String(new URL(window.location.href).searchParams.get("view") || "").trim();
    } catch (_error) {
      return "";
    }
  }

  updateBatchUrl(batchKey = "", options = {}) {
    const replace = Boolean(options && options.replace);
    const view = batchKey && options && options.view === "drawer" ? "drawer" : "";
    const url = new URL(window.location.href);
    const normalizedBatchKey = String(batchKey || "").trim();
    if (normalizedBatchKey) {
      url.searchParams.set("batch", normalizedBatchKey);
    } else {
      url.searchParams.delete("batch");
    }
    if (view) {
      url.searchParams.set("view", view);
    } else {
      url.searchParams.delete("view");
    }
    const nextUrl = `${url.pathname}${url.search}${url.hash}`;
    const currentUrl = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    if (nextUrl === currentUrl) return;
    const state = {
      ...(window.history.state || {}),
      overseasCostBatch: normalizedBatchKey,
      overseasCostView: view,
    };
    if (replace) {
      window.history.replaceState(state, "", nextUrl);
    } else {
      window.history.pushState(state, "", nextUrl);
    }
  }

  restoreBatchFocusStateFromUrl() {
    const batchKey = this.getBatchNameFromUrl();
    if (!batchKey) return null;
    const batch = this.findBatchByUrlKey(batchKey);
    if (!batch) {
      this.updateBatchUrl("", { replace: true });
      frappe.show_alert({ message: `链接中的批次不存在或已删除：${batchKey}`, indicator: "orange" });
      return null;
    }
    if (batchKey !== this.batchUrlKey(batch)) {
      this.updateBatchUrl(this.batchUrlKey(batch), { replace: true, view: this.getBatchViewFromUrl() });
    }
    if (!this.visibleBatches.some((row) => row.name === batch.name)) {
      this.resetFilterValues();
      this.visibleBatches = this.batches.slice();
    }
    this.activeBatchName = batch.name;
    this.exportPinnedBatchName = batch.name;
    this.dataCheckBatchName = batch.name;
    this.focusedBatchName = batch.name;
    this.expandedBatchNames = new Set([batch.name]);
    return batch;
  }

  async applyBatchFocusFromUrl() {
    const batchKey = this.getBatchNameFromUrl();
    const view = this.getBatchViewFromUrl();
    if (!batchKey) {
      this.clearBatchFocus({ updateUrl: false });
      return;
    }
    const batch = this.findBatchByUrlKey(batchKey);
    if (!batch) {
      frappe.show_alert({ message: `链接中的批次不存在或已删除：${batchKey}`, indicator: "orange" });
      return;
    }
    if (!this.visibleBatches.some((row) => row.name === batch.name)) {
      this.resetFilterValues();
      this.visibleBatches = this.batches.slice();
      this.renderTransportWorkbench();
    }
    await this.focusBatch(batch.name, { updateUrl: false });
    if (view === "drawer") {
      await this.openBatchDrawer(batch.name, { updateUrl: false });
    } else {
      this.closeBatchDrawer({ updateUrl: false });
    }
  }

  async setAllExpanded(expanded) {
    const displayBatches = this.getDisplayedBatches();
    if (expanded) {
      await this.prefetchBatchItems(displayBatches);
      this.expandedBatchNames = new Set(displayBatches.map((batch) => batch.name));
      this.addAudit("人工", "manual", "全部展开");
    } else {
      this.expandedBatchNames.clear();
      this.addAudit("系统", "system", "全部收起");
    }
    this.renderTable();
  }

  confirmDeleteBatch(batchName) {
    const batch = this.findBatch(batchName);
    if (!batch) return;
    const items = this.batchItems[batch.name] || [];
    const label = `${batch.customs_no || "--"} / ${batch.waybill_no || batch.batch_no || batch.name}`;
    frappe.confirm(
      `
        <div class="ocw-confirm-copy">
          <h4>确认删除报关/运单块？</h4>
          <p>将删除 ${this.escape(label)}，同时移除其下 ${items.length || batch.item_count || 0} 条物料明细。</p>
          <div class="ocw-confirm-note">删除后会同时清理该批次的版本、分摊规则、附件记录和修改记录。请仅删除测试或误导入数据。</div>
        </div>
      `,
      async () => {
        await this.deleteBatch(batch, label);
      }
    );
  }

  async deleteBatch(batch, label) {
    try {
      const result = await this.call(
        "overseas_costing.api.calculate.delete_batch",
        {
          batch_name: batch.name,
          remark: `前端删除批次：${label}`,
        },
        true
      );
      if (!result.ok) throw new Error(result.message || "批次删除失败");
      const counts = result.deleted_counts || {};
      const message = `批次已删除：物料 ${counts.item_count || 0}，版本 ${counts.version_count || 0}，规则 ${counts.rule_count || 0}`;
      frappe.show_alert({ message, indicator: "green" });
      if (this.activeBatchName === batch.name) this.activeBatchName = "";
      delete this.batchItems[batch.name];
      this.expandedBatchNames.delete(batch.name);
      await this.loadBatches();
    } catch (error) {
      this.showError(error);
    }
  }

  openAddBatchDialog() {
    const dialog = new frappe.ui.Dialog({
      title: "添加报关运单",
      fields: [
        { fieldtype: "Data", fieldname: "batch_no", label: "批次号/来源单号", reqd: 1 },
        { fieldtype: "Data", fieldname: "customs_no", label: "报关单号" },
        { fieldtype: "Data", fieldname: "waybill_no", label: "运单号/物流单号" },
        { fieldtype: "Data", fieldname: "container_no", label: "柜号" },
        { fieldtype: "Select", fieldname: "transport_mode", label: "运输方式", options: "海运\n空运\n快递", default: "海运" },
        {
          fieldtype: "Select",
          fieldname: "business_type",
          label: "业务类型",
          options: "海运正报正清\n海运 DDP（双清包税）\n空运 DDP（双清包税）\n正常空运\n快递",
          default: "海运正报正清",
        },
        { fieldtype: "Data", fieldname: "project_collection", label: "项目归集" },
        { fieldtype: "Data", fieldname: "source_approval_no", label: "钉钉审批编号" },
        { fieldtype: "Data", fieldname: "source_instance_id", label: "钉钉实例ID（procInstId）" },
        { fieldtype: "Small Text", fieldname: "source_dingtalk_url", label: "钉钉审批链接" },
        { fieldtype: "Small Text", fieldname: "source_remark", label: "备注" },
      ],
      primary_action_label: "确认新增",
      primary_action: (values) => {
        const batchPayload = {
          ...values,
          batch_no: String(values.batch_no || "").trim(),
          customs_no: String(values.customs_no || "").trim(),
          waybill_no: String(values.waybill_no || "").trim(),
          container_no: String(values.container_no || "").trim(),
          source_instance_id: String(values.source_instance_id || "").trim(),
          source_dingtalk_url: String(values.source_dingtalk_url || "").trim(),
        };
        const label = batchPayload.customs_no || batchPayload.waybill_no || batchPayload.batch_no;
        frappe.confirm(
          `
            <div class="ocw-confirm-copy">
              <h4>确认新增报关运单？</h4>
              <p>将新增「${this.escape(label || "未命名批次")}」空白批次。</p>
              <div class="ocw-confirm-note">新增后可继续添加物料或导入附件补数。</div>
            </div>
          `,
          async () => {
            const created = await this.createBatch(batchPayload);
            if (created) dialog.hide();
          }
        );
      },
    });
    dialog.show();
  }

  async createBatch(batchPayload) {
    try {
      const result = await this.call(
        "overseas_costing.api.batch.create_batch",
        {
          batch_payload: JSON.stringify(batchPayload),
        },
        true
      );
      if (!result.ok) throw new Error(result.message || "新增报关运单失败");
      this.resetFilterValues();
      this.activeBatchName = result.batch_name || "";
      await this.loadBatches();
      if (result.batch_name) {
        const batch = this.findBatch(result.batch_name);
        await this.loadBatchItems(result.batch_name, batch ? batch.current_version : result.version_name, true);
        this.expandedBatchNames.add(result.batch_name);
        this.renderTable();
        this.updateSearchResult();
      }
      frappe.show_alert({ message: result.message || "报关运单已新增", indicator: "green" });
      return true;
    } catch (error) {
      this.showError(error);
      return false;
    }
  }

  openAddMaterialDialog(batchName) {
    const batch = this.findBatch(batchName);
    if (!batch) return;
    this.activeBatchName = batch.name;
    this.exportPinnedBatchName = batch.name;
    const dialog = new frappe.ui.Dialog({
      title: "添加新物料",
      fields: [
        { fieldtype: "Data", fieldname: "material_code", label: "物料编码", reqd: 1 },
        { fieldtype: "Data", fieldname: "product_name", label: "物料名称（中文）", reqd: 1 },
        { fieldtype: "Data", fieldname: "product_name_es", label: "物料名称（西语）" },
        { fieldtype: "Data", fieldname: "spec_model", label: "规格型号 Especificación / Modelo" },
        { fieldtype: "Float", fieldname: "unit_price", label: "采购单价", default: 0 },
        { fieldtype: "Float", fieldname: "quantity", label: "采购数量", default: 1 },
        { fieldtype: "Data", fieldname: "unit", label: "单位" },
        { fieldtype: "Data", fieldname: "recipient", label: "收件人" },
        { fieldtype: "Data", fieldname: "import_name", label: "海关进口名称" },
        { fieldtype: "Data", fieldname: "hs_code", label: "海关分类编码" },
        { fieldtype: "Data", fieldname: "category", label: "大类分类" },
      ],
      primary_action_label: "确认新增",
      primary_action: (values) => {
        const itemPayload = {
          ...values,
          transport_mode: batch.transport_mode || "SEA",
          customs_no: batch.customs_no || "",
          waybill_no: batch.waybill_no || "",
          goods_value: Number(values.unit_price || 0) * Number(values.quantity || 0),
        };
        frappe.confirm(
          `
            <div class="ocw-confirm-copy">
              <h4>确认新增物料？</h4>
              <p>将在 ${this.escape(batch.waybill_no || batch.batch_no || batch.name)} 下新增「${this.escape(values.product_name || values.material_code)}」。</p>
            </div>
          `,
          async () => {
            const created = await this.createMaterial(batch, itemPayload);
            if (created) dialog.hide();
          }
        );
      },
    });
    dialog.show();
  }

  async createMaterial(batch, itemPayload) {
    try {
      const result = await this.call(
        "overseas_costing.api.calculate.create_item",
        {
          batch_name: batch.name,
          version_name: batch.current_version,
          item_payload: JSON.stringify(itemPayload),
          remark: "前端添加新物料",
        },
        true
      );
      if (!result.ok) throw new Error(result.message || "新增物料失败");
      this.markBatchDirty(batch.name);
      this.resetFilterValues();
      await this.loadBatchItems(batch.name, batch.current_version, true);
      await this.loadAuditLogs(batch.name, batch.current_version);
      this.expandedBatchNames.add(batch.name);
      this.renderTable();
      this.updateSearchResult();
      frappe.show_alert({ message: result.message || "物料已新增", indicator: "green" });
      return true;
    } catch (error) {
      this.showError(error);
      return false;
    }
  }

  confirmDeleteMaterial(batchName, itemName, itemLabel) {
    const batch = this.findBatch(batchName);
    if (!batch || !itemName) return;
    frappe.confirm(
      `
        <div class="ocw-confirm-copy">
          <h4>确认删除物料？</h4>
          <p>将从 ${this.escape(batch.waybill_no || batch.batch_no || batch.name)} 下删除物料：${this.escape(itemLabel || itemName)}。</p>
          <div class="ocw-confirm-note">删除后批次会标记为 Dirty，并写入修改记录。</div>
        </div>
      `,
      async () => {
        await this.deleteMaterial(batch, itemName, itemLabel);
      }
    );
  }

  async deleteMaterial(batch, itemName, itemLabel) {
    try {
      const result = await this.call(
        "overseas_costing.api.calculate.delete_item",
        {
          item_name: itemName,
          batch_name: batch.name,
          version_name: batch.current_version,
          remark: `前端删除物料：${itemLabel || itemName}`,
        },
        true
      );
      if (!result.ok) throw new Error(result.message || "删除物料失败");
      this.markBatchDirty(batch.name);
      await this.loadBatchItems(batch.name, batch.current_version, true);
      await this.loadAuditLogs(batch.name, batch.current_version);
      this.expandedBatchNames.add(batch.name);
      this.renderTable();
      frappe.show_alert({ message: result.message || "物料已删除", indicator: "green" });
    } catch (error) {
      this.showError(error);
    }
  }

  startCellEdit($cell, event = null, autoOpenSelect = false) {
    if (event) {
      event.preventDefault();
      event.stopPropagation();
    }
    if (!$cell.length || $cell.data("saving") || $cell.hasClass("is-editing")) return;
    if ($cell.attr("data-editable-cell") !== "1") return;

    const fieldname = $cell.attr("data-fieldname");
    const oldValue = $cell.attr("data-raw-value") || "";
    const label = $cell.attr("data-field-label") || fieldname;
    const isNumeric = this.isNumericField(fieldname);
    const options = this.selectOptions[fieldname] || null;
    const selectedValue = options ? this.normalizeSelectValue(fieldname, oldValue) : oldValue;

    $cell.removeData("cancelled saving");
    $cell.data("original-html", $cell.html());
    $cell.addClass("is-editing");

    if (options) {
      const hasSelectedOption = options.some((option) => String(option) === selectedValue);
      const emptyOption = selectedValue ? "" : `<option value="" selected>请选择</option>`;
      const currentOption =
        selectedValue && !hasSelectedOption
          ? `<option value="${this.escape(selectedValue)}" selected>${this.escape(this.selectOptionLabel(fieldname, selectedValue))}</option>`
          : "";
      const optionHtml = options
        .map(
          (option) =>
            `<option value="${this.escape(option)}" ${String(option) === selectedValue ? "selected" : ""}>${this.escape(this.selectOptionLabel(fieldname, option))}</option>`
        )
        .join("");
      $cell.html(`<select class="ocw-cell-editor ocw-cell-select" aria-label="${this.escape(label)}">${emptyOption}${currentOption}${optionHtml}</select>`);
    } else {
      $cell.html(`
        <input
          class="ocw-cell-editor"
          aria-label="${this.escape(label)}"
          value="${this.escape(oldValue)}"
          ${isNumeric ? 'inputmode="decimal"' : ""}
        />
      `);
    }

    const editor = $cell.find(".ocw-cell-editor").get(0);
    if (editor) {
      if (autoOpenSelect && options && typeof editor.showPicker === "function") {
        editor.focus();
        try {
          editor.showPicker();
          return;
        } catch (error) {
          // Some browsers only allow showPicker in stricter user-gesture windows.
        }
      }
      window.requestAnimationFrame(() => {
        editor.focus();
        if (editor.setSelectionRange && editor.value !== undefined) {
          const pos = String(editor.value).length;
          editor.setSelectionRange(pos, pos);
        }
      });
    }
  }

  cancelCellEdit($cell) {
    if (!$cell.length || !$cell.hasClass("is-editing")) return;
    $cell.data("cancelled", true);
    $cell.removeData("saving committing");
    $cell.removeClass("is-editing is-saving");
    $cell.html($cell.data("original-html") || this.renderCell($cell.attr("data-raw-value"), { fieldname: $cell.attr("data-fieldname") }));
  }

  async commitCellEdit($cell) {
    if (!$cell.length || !$cell.hasClass("is-editing") || $cell.data("saving") || $cell.data("committing") || $cell.data("cancelled")) {
      $cell.removeData("cancelled");
      return;
    }
    $cell.data("committing", true);

    const $editor = $cell.find(".ocw-cell-editor");
    const oldValue = $cell.attr("data-raw-value") || "";
    const fieldname = $cell.attr("data-fieldname");
    const newValue = this.selectOptions[fieldname] ? this.normalizeSelectValue(fieldname, $editor.val()) : this.normalizeEditorValue($editor.val());
    const oldComparableValue = this.selectOptions[fieldname] ? this.normalizeSelectValue(fieldname, oldValue) : oldValue;
    const fieldLabel = $cell.attr("data-field-label") || fieldname;
    const batchName = $cell.attr("data-batch-name");
    const itemName = $cell.attr("data-item-name");
    const versionName = $cell.attr("data-version-name") || null;
    const isSpecialOverride = $cell.attr("data-special-override") === "1";
    const itemLabel = this.getLocalItemLabel(batchName, itemName);

    if (newValue === oldComparableValue) {
      this.cancelCellEdit($cell);
      return;
    }

    const confirmed = await this.requestEditConfirm(fieldLabel, this.formatCellValue(newValue, { fieldname }));
    if (!confirmed) {
      this.cancelCellEdit($cell);
      return;
    }

    let remark = "";
    if (isSpecialOverride) {
      remark = await this.requestEditRemark(fieldLabel);
      if (!remark) {
        this.cancelCellEdit($cell);
        return;
      }
    }

    $cell.data("saving", true).addClass("is-saving").html(`<span class="ocw-cell-saving">保存中</span>`);
    try {
      const result = await this.call(
        "overseas_costing.api.calculate.update_item_field",
        {
          item_name: itemName,
          fieldname,
          value: newValue,
          version_name: versionName,
          remark,
        },
        true
      );
      if (!result.ok) {
        throw new Error(result.message || "字段保存失败");
      }
      this.activeBatchName = batchName;
      this.markBatchDirty(batchName);
      this.updateLocalItemValue(batchName, itemName, fieldname, result.value);
      await this.loadBatchItems(batchName, versionName, true);
      await this.loadAuditLogs(batchName, versionName);
      this.renderTable();
      frappe.show_alert({ message: result.message || "字段已保存", indicator: result.changed ? "green" : "blue" });
    } catch (error) {
      $cell.removeData("saving committing");
      this.cancelCellEdit($cell);
      this.showError(error);
    }
  }

  requestEditConfirm(fieldLabel, newValue) {
    return new Promise((resolve) => {
      frappe.confirm(
        `
          <div class="ocw-confirm-copy">
            <h4>确认修改</h4>
            <p>确认将「${this.escape(fieldLabel)}」修改为「${this.escape(this.formatValue(newValue))}」？</p>
          </div>
        `,
        () => resolve(true),
        () => resolve(false)
      );
    });
  }

  requestEditRemark(fieldLabel) {
    return new Promise((resolve) => {
      let settled = false;
      const dialog = new frappe.ui.Dialog({
        title: "填写修改原因",
        fields: [
          {
            fieldtype: "Small Text",
            fieldname: "remark",
            label: `${fieldLabel} 修改原因`,
            reqd: 1,
          },
        ],
        primary_action_label: "保存",
        primary_action: (values) => {
          settled = true;
          dialog.hide();
          resolve(String(values.remark || "").trim());
        },
      });
      dialog.onhide = () => {
        if (!settled) resolve("");
      };
      dialog.show();
    });
  }

  markBatchDirty(batchName) {
    const batch = this.findBatch(batchName);
    if (batch) batch.status = "Dirty";
  }

  updateLocalItemValue(batchName, itemName, fieldname, value) {
    const items = this.batchItems[batchName] || [];
    const row = items.find((item) => item.name === itemName);
    if (!row) return;
    row[fieldname] = value;
    row.manual_override_flag = 1;
  }

  getLocalItemLabel(batchName, itemName) {
    const items = this.batchItems[batchName] || [];
    const row = items.find((item) => item.name === itemName);
    if (!row) return "";
    return this.materialAuditLabel(row);
  }

  materialAuditLabel(row) {
    if (!row) return "";
    const code = row.material_code || "";
    const name = row.product_name || "";
    if (code && name) return `${code} / ${name}`;
    return code || name || row.name || "未命名物料";
  }

  hasActiveFilters() {
    return Object.keys(this.filters).some((key) => {
      if (key === "start_date" || key === "end_date") return !this.hasDefaultDateRange();
      return String(this.filters[key] || "").trim() !== "";
    });
  }

  workRoleInfo(role = this.workRole) {
    if (role === "finance") {
      return {
        key: "finance",
        label: "财务",
        title: "财务待核算",
        blockName: "待核算批次",
        description: "处理数据已完整批次：核对费用、重新试算并确认结果。",
        empty: "当前没有数据已完整的待核算批次",
      };
    }
    return {
      key: "purchase",
      label: "采购",
      title: "采购待补资料",
      blockName: "待补资料批次",
      description: "处理数据不完整批次：补齐采购、装箱单和物流资料。",
      empty: "当前没有数据不完整的待补资料批次",
    };
  }

  batchDataCompleteness(batch = {}, items = [], hasLoadedItems = false) {
    const sourceStatus = batch.source_status || {};
    const reasons = [];
    const itemRows = hasLoadedItems ? items : [];
    const itemCount = hasLoadedItems ? itemRows.length : Number(batch.item_count || 0);
    const approvalState = String(sourceStatus.purchase_approval_sync_state || "").trim().toLowerCase();

    if (sourceStatus.invalid_business || approvalState === "invalid") reasons.push("采购审批无效");
    if (!this.hasText(batch.subsidiary_code)) reasons.push("缺业务主体");
    if (approvalState === "missing") reasons.push("未关联采购审批");
    if (approvalState === "pending") reasons.push("采购审批状态未同步");
    if (!itemCount) reasons.push("缺少物料明细");
    if (hasLoadedItems) {
      const missingItem = itemRows.filter((row) => !this.hasText(row.material_code) || !this.hasText(row.product_name) || !this.isPositive(row.quantity)).length;
      const missingPurchase = itemRows.filter((row) => !this.isPositive(row.unit_price) || !this.hasText(row.purchase_currency) || !this.isPositive(row.goods_value)).length;
      const missingShipping = itemRows.filter((row) => !this.isPositive(row.actual_shipped_qty) || !this.isPositive(row.gross_weight_kg)).length;
      if (missingItem) reasons.push(`物料基础字段缺 ${missingItem} 行`);
      if (missingPurchase) reasons.push(`采购金额字段缺 ${missingPurchase} 行`);
      if (missingShipping) reasons.push(`实际数量/毛重缺 ${missingShipping} 行`);
    } else if (itemCount) {
      reasons.push("待展开明细核对");
    }

    return {
      value: reasons.length ? "数据不完整" : "数据已完整",
      hint: reasons.length ? reasons.join("；") : "业务主体、采购审批、物料、采购金额和发货基础数据已具备",
      className: reasons.length ? "warn" : "ok",
      complete: !reasons.length,
      reasons,
    };
  }

  matchesWorkRole(batch, items) {
    const hasLoadedItems = Object.prototype.hasOwnProperty.call(this.batchItems, batch.name);
    const complete = this.batchDataCompleteness(batch, items, hasLoadedItems).complete;
    return this.workRole === "finance" ? complete : !complete;
  }

  filterBatches({ ignoreTransport = false, ignoreBusinessType = false } = {}) {
    const customs = this.lower(this.filters.customs_no);
    const waybill = this.lower(this.filters.waybill_no);
    const subsidiary = this.lower(this.filters.subsidiary_code);
    const businessType = ignoreBusinessType ? "" : String(this.filters.business_type || "").trim().toUpperCase();
    const calculationStatus = this.lower(this.filters.calculation_status);
    const erpStatus = this.lower(this.filters.erp_status);
    const transportMode = ignoreTransport ? "" : this.normalizeTransportMode(this.filters.transport_mode);
    const itemFilters = ["material_code", "product_name", "import_name", "hs_code", "category"];
    return this.sortBatchesNewestFirst(this.batches.filter((batch) => {
      const items = this.batchItems[batch.name] || [];
      if (!this.matchesWorkRole(batch, items)) return false;
      if (transportMode && this.batchTransportMode(batch, items) !== transportMode) return false;
      if (subsidiary && !this.lower(batch.subsidiary_code).includes(subsidiary)) return false;
      if (businessType && this.batchBusinessType(batch, items) !== businessType) return false;
      if (calculationStatus) {
        const confirmed = String(batch.confirm_status || batch.status || "").toLowerCase().includes("confirmed");
        const statusText = `${batch.status || ""} ${batch.confirm_status || ""} ${this.batchStatusInfo(batch.status, batch, items.length).label} ${
          confirmed ? "已确认" : ""
        }`;
        if (!this.lower(statusText).includes(calculationStatus)) return false;
      }
      if (erpStatus && this.erpWritebackQueueKey(batch) !== erpStatus) return false;
      const customsMatched = !customs || this.batchMatchesQuery(batch, items, customs, [
        "customs_no",
        "waybill_no",
        "container_no",
        "batch_no",
        "source_approval_no",
        "source_instance_id",
        "source_dingtalk_url",
        "source_file_name",
      ]);
      const waybillMatched = !waybill || this.batchMatchesQuery(batch, items, waybill, [
        "waybill_no",
        "container_no",
        "sea_bill_no",
        "commercial_invoice_no",
        "batch_no",
        "source_approval_no",
        "source_instance_id",
        "source_dingtalk_url",
      ]);
      if (!customsMatched || !waybillMatched) return false;
      return itemFilters.every((fieldname) => {
        const needle = this.lower(this.filters[fieldname]);
        if (!needle) return true;
        return items.some((item) => this.itemMatchesField(item, fieldname, needle));
      });
    }));
  }

  sortBatchesNewestFirst(batches) {
    return (batches || []).slice().sort((left, right) => this.batchSortTime(right) - this.batchSortTime(left));
  }

  batchSortTime(batch) {
    const value = batch && (batch.source_created_at || batch.creation || batch.modified);
    if (!value) return 0;
    const parsed = Date.parse(String(value).replace(" ", "T"));
    return Number.isFinite(parsed) ? parsed : 0;
  }

  batchMatchesQuery(batch, items, needle, batchFields) {
    if (!needle) return true;
    const sourceStatus = batch.source_status || {};
    const batchValues = [
      ...batchFields.map((fieldname) => batch[fieldname]),
      sourceStatus.source_no,
      sourceStatus.source_approval_status,
    ];
    if (batchValues.some((value) => this.lower(value).includes(needle))) return true;
    return (items || []).some((item) =>
      [
        item.customs_no,
        item.waybill_no,
        item.source_doc_no,
        item.source_file_name,
        item.source_attachment_id,
        item.dingtalk_instance_id,
        item.dingtalk_official_url,
      ].some((value) => this.lower(value).includes(needle))
    );
  }

  itemMatchesField(item, fieldname, needle) {
    const aliases = {
      material_code: ["material_code", "source_doc_no"],
      product_name: ["product_name", "product_name_es", "spec_model"],
      import_name: ["import_name", "product_name", "product_name_es"],
      hs_code: ["hs_code"],
      category: ["category", "project_collection"],
    };
    const fields = aliases[fieldname] || [fieldname];
    return fields.some((name) => this.lower(item[name]).includes(needle));
  }

  batchTransportMode(batch, items = null) {
    const rows = items || this.batchItems[batch.name] || [];
    return this.normalizeTransportMode(batch.transport_mode || (rows[0] || {}).transport_mode);
  }

  batchBusinessType(batch, items = null) {
    const rows = items || this.batchItems[batch.name] || [];
    const raw = batch.business_type || (rows[0] || {}).business_type || "";
    return String(raw || "").trim().toUpperCase();
  }

  businessTypeLabel(value) {
    const labels = {
      SEA_STANDARD: "\u6d77\u8fd0\u6b63\u62a5\u6b63\u6e05",
      SEA_DDP: "\u6d77\u8fd0 DDP\uff08\u53cc\u6e05\u5305\u7a0e\uff09",
      AIR_DDP: "\u7a7a\u8fd0 DDP\uff08\u53cc\u6e05\u5305\u7a0e\uff09",
      AIR_STANDARD: "\u6b63\u5e38\u7a7a\u8fd0",
      EXPRESS: "\u5feb\u9012",
    };
    const key = String(value || "").trim().toUpperCase();
    return labels[key] || String(value || "");
  }

  businessTypeCompactLabel(value) {
    const labels = {
      SEA_STANDARD: "\u6d77\u8fd0\u6b63\u6e05",
      SEA_DDP: "\u6d77\u8fd0\u53cc\u6e05",
      AIR_DDP: "\u7a7a\u8fd0\u53cc\u6e05",
      AIR_STANDARD: "\u6b63\u5e38\u7a7a\u8fd0",
      EXPRESS: "\u5feb\u9012",
    };
    const key = String(value || "").trim().toUpperCase();
    return labels[key] || this.businessTypeLabel(value);
  }

  countVisibleItems() {
    return this.visibleBatches.reduce((total, batch) => total + (this.batchItems[batch.name] || []).length, 0);
  }

  currentBatchLabel() {
    return this.currentBatchNo() ? `${this.currentBatchNo()} 明细` : "明细";
  }

  currentBatchNo() {
    const row = this.getActiveBatch();
    return row ? row.batch_no || row.name : "";
  }

  batchReferenceLabel(batch) {
    if (!batch) return "未选择批次";
    return batch.customs_no || batch.waybill_no || batch.batch_no || batch.name || "未命名批次";
  }

  voucherBatchHint(batch) {
    return batch
      ? "文件会优先按报关单号或柜号自动匹配；所选批次用于当前对比和查看已保存记录。"
      : "文件会按报关单号或柜号自动尝试匹配批次。";
  }

  renderBatchOptions(selectedBatchName = "") {
    return this.batches
      .map((batch) => {
        const selected = batch.name === selectedBatchName ? " selected" : "";
        return `<option value="${this.escape(batch.name)}"${selected}>${this.escape(this.batchReferenceLabel(batch))}</option>`;
      })
      .join("");
  }

  getSelectableBatches() {
    if (this.hasActiveFilters()) return this.visibleBatches;
    return this.visibleBatches.length ? this.visibleBatches : this.batches;
  }

  getSelectableBatch(batchName = "", batches = null) {
    const options = batches || this.getSelectableBatches();
    if (!options.length) return null;
    return (
      options.find((batch) => batch.name === batchName) ||
      options.find((batch) => batch.name === this.activeBatchName) ||
      options[0] ||
      null
    );
  }

  findSelectableBatch(batchName, batches = null) {
    const options = batches || this.getSelectableBatches();
    return options.find((batch) => batch.name === batchName) || null;
  }

  renderSelectableBatchOptions(selectedBatchName = "", batches = null) {
    const options = batches || this.getSelectableBatches();
    if (!options.length) return `<option value="">当前筛选无批次</option>`;
    return options
      .map((batch) => {
        const selected = batch.name === selectedBatchName ? " selected" : "";
        return `<option value="${this.escape(batch.name)}"${selected}>${this.escape(this.batchReferenceLabel(batch))}</option>`;
      })
      .join("");
  }

  scopedBatchHint() {
    return this.hasActiveFilters()
      ? "仅显示当前筛选范围内的批次；可输入批次号、报关单号或钉钉审批编号查询历史批次。"
      : `默认显示最近 ${this.defaultRecentDays} 天批次；可输入批次号、报关单号或钉钉审批编号查询历史批次。`;
  }

  renderVisibleBatchOptions(selectedBatchName = "") {
    return this.renderSelectableBatchOptions(selectedBatchName, this.visibleBatches);
  }

  getDataCheckBatch() {
    const selectableBatches = this.getSelectableBatches();
    if (!selectableBatches.length) return null;
    return (
      selectableBatches.find((batch) => batch.name === this.dataCheckBatchName) ||
      this.getSelectableBatch(this.activeBatchName, selectableBatches) ||
      null
    );
  }

  renderDataCheckBatchSelector(batch) {
    const $select = this.$root.find("[data-role='data-check-batch-select']");
    if (!$select.length) return;
    const selectableBatches = this.getSelectableBatches();
    const selectedBatchName = batch ? batch.name : "";
    $select.html(this.renderSelectableBatchOptions(selectedBatchName, selectableBatches));
    $select.prop("disabled", !selectableBatches.length);
  }

  getActiveBatch() {
    return this.findBatch(this.activeBatchName) || this.visibleBatches[0] || this.batches[0] || null;
  }

  getVisibleActiveBatch() {
    return (
      this.visibleBatches.find((batch) => batch.name === this.activeBatchName) ||
      this.visibleBatches[0] ||
      this.findBatch(this.activeBatchName) ||
      null
    );
  }

  findBatch(batchName) {
    return this.batches.find((batch) => batch.name === batchName);
  }

  batchUrlKey(batch) {
    if (!batch) return "";
    return String(batch.batch_no || batch.customs_no || batch.waybill_no || batch.name || "").trim();
  }

  findBatchByUrlKey(value) {
    const key = String(value || "").trim();
    if (!key) return null;
    return (
      this.batches.find((batch) => String(batch.batch_no || "").trim() === key) ||
      this.batches.find((batch) => String(batch.customs_no || "").trim() === key) ||
      this.batches.find((batch) => String(batch.waybill_no || "").trim() === key) ||
      this.findBatch(key) ||
      null
    );
  }

  versionLabel(version) {
    if (!version) return "";
    const type = version.version_type || "";
    if (type === "ESTIMATED") return "暂估版";
    if (type === "ACTUAL") return "实际版";
    if (type === "Estimated") return "暂估版";
    if (type === "Actual") return "实际版";
    return version.version_code || type || "";
  }

  normalizeTransportMode(value) {
    const text = String(value || "").trim();
    if (!text) return "";
    const upper = text.toUpperCase();
    if (["SEA", "OCEAN", "OCEAN_FREIGHT", "海运"].includes(upper) || text.includes("海运")) return "SEA";
    if (["AIR", "AIR_FREIGHT", "空运"].includes(upper) || text.includes("空运")) return "AIR";
    if (["EXPRESS", "COURIER", "快递"].includes(upper) || text.includes("快递") || upper.includes("CORREO EXPRESS")) {
      return "EXPRESS";
    }
    return upper;
  }

  transportLabel(value) {
    if (!value) return "未指定";
    const labels = {
      SEA: "海运",
      AIR: "空运",
      EXPRESS: "快递",
    };
    const key = this.normalizeTransportMode(value);
    return labels[key] || String(value);
  }

  formatLogisticsTextSummary(summary) {
    if (!summary || typeof summary !== "object") return "";
    const parts = [];
    const quoteAmount = Number(summary.logistics_quote_amount);
    const quoteCurrency = summary.logistics_quote_currency || "RMB";
    const carrier = summary.logistics_quote_carrier || "";
    if (Number.isFinite(quoteAmount) && quoteAmount > 0) {
      parts.push(`${carrier ? `${carrier} ` : ""}${this.formatNumber(quoteAmount)} ${quoteCurrency}`);
    }
    const mode = summary.transport_mode || summary.transport_mode_raw;
    if (this.hasText(mode)) parts.push(this.transportLabel(mode));
    if (this.hasText(summary.pre_delivery_date)) parts.push(`预计 ${summary.pre_delivery_date}`);
    if (this.hasText(summary.destination)) parts.push(summary.destination);
    const grossWeight = Number(summary.gross_weight_kg);
    if (Number.isFinite(grossWeight) && grossWeight > 0) parts.push(`${this.formatNumber(grossWeight)} KG`);
    if (!parts.length) return "";
    const suffix = summary.ai_used ? "（AI辅助）" : "";
    return `${parts.join("；")}${suffix}`;
  }

  selectOptionLabel(fieldname, value) {
    if (fieldname === "purchase_currency") return this.currencyLabel(value);
    if (fieldname === "transport_mode") return this.transportLabel(value);
    return String(value || "");
  }

  normalizeSelectValue(fieldname, value) {
    if (fieldname === "purchase_currency") return this.normalizeCurrencyCode(value);
    if (fieldname === "transport_mode") return this.normalizeTransportMode(value);
    return this.normalizeEditorValue(value);
  }

  normalizeCurrencyCode(value) {
    const text = String(value || "").trim();
    if (!text) return "";
    const compact = text.replace(/\s+/g, "").toLowerCase();
    if (compact.includes("rmb") || compact.includes("cny") || compact.includes("人民币")) return "RMB";
    if (compact.includes("usd") || compact.includes("dólar") || compact.includes("dolar") || compact.includes("美元") || compact.includes("美金")) {
      return "USD";
    }
    if (compact.includes("mxn") || compact.includes("peso") || compact.includes("pesos") || compact.includes("比索") || compact.includes("墨西哥")) {
      return "MXN";
    }
    return text.toUpperCase();
  }

  parseJsonObject(value) {
    if (!value) return {};
    if (typeof value === "object") return value && !Array.isArray(value) ? value : {};
    try {
      const parsed = JSON.parse(String(value));
      return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
    } catch (_error) {
      return {};
    }
  }

  currencyLabel(value) {
    if (!value) return "";
    const labels = {
      RMB: "人民币",
      CNY: "人民币",
      USD: "美元",
      MXN: "比索",
    };
    const code = this.normalizeCurrencyCode(value);
    return labels[code] || String(value);
  }

  batchStatusInfo(status, batch = {}, itemCount = null) {
    const value = String(status || "").trim();
    const normalized = value.toLowerCase();
    const sourceType = String(batch.source_type || "").trim();
    const count = itemCount === null ? Number(batch.item_count || 0) : Number(itemCount || 0);
    if (normalized.includes("imported")) {
      const isOaTraceOnly = sourceType === "oa_logistics" && !count;
      return {
        label: isOaTraceOnly ? "仅拉取审批" : "已导入",
        statusClass: isOaTraceOnly ? "ocw-check-info" : "ocw-check-ok",
        needsRecalculate: false,
        suggestion: isOaTraceOnly ? "已保存审批追溯，后续解析附件后生成明细" : "数据已导入，可继续核对或试算",
      };
    }
    if (normalized.includes("dirty")) {
      return {
        label: "待重算",
        statusClass: "ocw-check-warn",
        needsRecalculate: true,
        suggestion: "明细已修改，重算后再复核综合成本",
      };
    }
    if (normalized.includes("calculated")) {
      return {
        label: "已试算",
        statusClass: "ocw-check-ok",
        needsRecalculate: false,
        suggestion: "可继续核对运费/税费/杂费和分摊结果",
      };
    }
    if (normalized.includes("draft")) {
      return {
        label: "草稿",
        statusClass: "ocw-check-info",
        needsRecalculate: true,
        suggestion: "导入或补数后点击重新试算",
      };
    }
    return {
      label: value || "待处理",
      statusClass: "ocw-check-info",
      needsRecalculate: false,
      suggestion: "继续核对字段完整性",
    };
  }

  statusClass(status) {
    const value = String(status || "").toLowerCase();
    if (value.includes("calculated")) return "done";
    if (value.includes("dirty")) return "review";
    if (value.includes("draft")) return "review";
    if (value.includes("imported")) return "done";
    if (value.includes("locked")) return "locked";
    return "active";
  }

  columnAlignClass(column) {
    return this.isNumericField(column.fieldname) ? "is-right" : "is-left";
  }

  isEditableColumn(column) {
    return Boolean(column && column.fieldname && !this.readonlyCalcFields.has(column.fieldname));
  }

  columnWidthClass(column, index) {
    if (index === 0) return "ocw-col-code";
    if (index === 1) return "ocw-col-product";
    if (["import_name", "product_name", "spec_model"].includes(column.fieldname)) return "ocw-col-long";
    if (this.isNumericField(column.fieldname)) return "ocw-col-number";
    return "ocw-col-short";
  }

  isNumericField(fieldname) {
    return [
      "unit_price",
      "quantity",
      "goods_value",
      "china_misc_rmb",
      "china_misc_mxn",
      "china_ocean_usd",
      "cc_rate",
      "cc_anti_dumping",
      "igi_rate",
      "igi_amount",
      "iva_rate",
      "iva_amount",
      "goods_value_ratio",
      "dta",
      "prv_duty",
      "prv_iva",
      "import_tax_total",
      "revalidacion",
      "maniobras",
      "muellaje",
      "entrega_mercancia",
      "previo",
      "service_aa",
      "almacenajes",
      "reconocimiento_aduanero",
      "honorarios",
      "complemento_maniobras",
      "desconsolidacion",
      "maniobra_falso",
      "arrastre",
      "patio_regulador",
      "entrega_vacio",
      "limpieza_contenedor",
      "mexico_customs_mxn",
      "mexico_customs_rmb",
      "mexico_customs_usd",
      "mexico_inland_mxn",
      "mexico_misc_mxn",
      "mexico_inland_misc_rmb",
      "china_to_mexico_freight_rmb",
      "gross_weight_kg",
      "weight_ratio",
      "freight_alloc_rmb",
      "freight_alloc_mxn",
      "total_logistics_mxn",
      "alloc_price_mxn",
      "total_cost_rmb",
      "total_unit_rmb",
    ].includes(fieldname);
  }

  firstBatchValue(batchName, fieldname) {
    const items = this.batchItems[batchName] || [];
    const found = items.find((row) => row[fieldname] !== null && row[fieldname] !== undefined && row[fieldname] !== "");
    return found ? found[fieldname] : "";
  }

  sumBatchNumber(batchName, fieldname) {
    const items = this.batchItems[batchName] || [];
    return items.reduce((total, row) => {
      const number = Number(row[fieldname]);
      return Number.isFinite(number) ? total + number : total;
    }, 0);
  }

  sumRowsNumber(rows, fieldname) {
    return (rows || []).reduce((total, row) => {
      const number = Number(row[fieldname]);
      return Number.isFinite(number) ? total + number : total;
    }, 0);
  }

  firstLoadedValue(rows, fieldname) {
    const found = (rows || []).find((row) => this.hasText(row[fieldname]));
    return found ? found[fieldname] : "";
  }

  countRows(rows, predicate) {
    return (rows || []).reduce((total, row) => (predicate(row) ? total + 1 : total), 0);
  }

  describeProblemRows(rows, predicate, limit = 3) {
    const matches = [];
    (rows || []).forEach((row, index) => {
      if (predicate(row)) {
        matches.push(this.itemLocationLabel(row, index));
      }
    });
    if (!matches.length) return "";
    const head = matches.slice(0, limit).join("、");
    const tail = matches.length > limit ? ` 等 ${matches.length} 行` : "";
    return `${head}${tail}`;
  }

  itemLocationLabel(row, index = 0) {
    const rowNo = row.excel_row_no || row.row_no || index + 1;
    const material = this.materialAuditLabel(row);
    return `第 ${rowNo} 行 ${material}`;
  }

  hasText(value) {
    return String(value || "").trim() !== "";
  }

  isPositive(value) {
    const number = Number(value);
    return Number.isFinite(number) && number > 0;
  }

  lower(value) {
    return String(value || "").toLowerCase();
  }

  shouldShowEmptyZeroFee(fieldname, value) {
    if (!["limpieza_contenedor"].includes(fieldname)) return false;
    const number = Number(value);
    return Number.isFinite(number) && number === 0;
  }

  formatCellValue(value, column) {
    if (column.fieldname === "transport_mode") return this.transportLabel(value);
    if (column.fieldname === "purchase_currency") return this.currencyLabel(value);
    if (this.shouldShowEmptyZeroFee(column.fieldname, value)) return "";
    if (this.isNumericField(column.fieldname)) return this.formatNumber(value);
    return this.formatValue(value);
  }

  formatValue(value) {
    if (value === null || value === undefined || value === "") return "";
    if (typeof value === "number") return this.formatNumber(value);
    return String(value);
  }

  formatDateTimeMinute(value) {
    const text = String(value || "").trim();
    if (!text) return "";
    const match = text.match(/^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})/);
    if (match) return `${match[1]} ${match[2]}`;
    return text;
  }

  formatAuditValue(value) {
    if (value === null || value === undefined || value === "") return "空";
    if (typeof value === "object") return JSON.stringify(value);
    const text = String(value);
    const number = Number(text.replace(/,/g, ""));
    if (text.trim() !== "" && Number.isFinite(number) && /^-?\d+(\.\d+)?$/.test(text.replace(/,/g, ""))) {
      return this.formatNumber(number);
    }
    return text;
  }

  formatNumber(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return value === undefined || value === null ? "" : String(value);
    return number.toLocaleString("zh-CN", { maximumFractionDigits: 6 });
  }

  normalizeEditorValue(value) {
    if (value === null || value === undefined) return "";
    return String(value).replace(/,/g, "").trim();
  }

  getDefaultPullDateRange() {
    const endDate = new Date();
    const startDate = new Date(endDate);
    startDate.setDate(startDate.getDate() - (this.defaultRecentDays - 1));
    return {
      start_date: this.formatDateInput(startDate),
      end_date: this.formatDateInput(endDate),
    };
  }

  formatDateInput(date) {
    const pad = (value) => String(value).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  }

  nowText() {
    const date = new Date();
    const pad = (value) => String(value).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }

  escape(value) {
    return String(value === null || value === undefined ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  showError(error) {
    const message = this.normalizeErrorMessage(error);
    const dialog = new frappe.ui.Dialog({
      title: "操作失败",
      fields: [
        {
          fieldtype: "HTML",
          fieldname: "error_detail",
          options: `
            <div class="ocw-error-dialog">
              <div class="ocw-error-title">海外采购综合成本核算</div>
              <div class="ocw-error-message">${this.escape(message)}</div>
            </div>
          `,
        },
      ],
      primary_action_label: "我知道了",
      primary_action: () => dialog.hide(),
    });
    dialog.show();
    dialog.$wrapper.addClass("ocw-error-modal");
  }

  normalizeErrorMessage(error) {
    const raw = this.extractReadableError(error);
    let message = raw ? String(raw) : "操作失败";
    message = message.replace(/^Server Error\s*/i, "").trim() || "操作失败";
    message = message.replace(/^ValueError:\s*/i, "");
    if (message.includes("工作簿中不存在工作表")) {
      message += "\n\n建议：工作表名称可以留空，由系统自动识别；只有一个工作表的文件会自动使用该工作表。";
    }
    return message;
  }

  extractReadableError(error) {
    if (!error) return "";
    if (typeof error === "string") return error;
    if (error.message && typeof error.message === "string" && error.message !== "[object Object]") {
      return error.message;
    }
    const response = error.responseJSON || error.responseText || error.xhr?.responseJSON || error.xhr?.responseText;
    const serverMessage = this.extractServerMessage(response);
    if (serverMessage) return serverMessage;
    if (error._server_messages || error.exception || error.exc || error.statusText) {
      return this.extractServerMessage(error) || error.exception || error.exc || error.statusText;
    }
    try {
      return JSON.stringify(error);
    } catch (_error) {
      return "操作失败";
    }
  }
}
