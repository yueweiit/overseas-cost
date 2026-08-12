frappe.pages["overseas-cost-workbench"] = frappe.pages["overseas-cost-workbench"] || {};

frappe.pages["overseas-cost-workbench"].on_page_load = function (wrapper) {
  const workbench = new OverseasCostWorkbench(wrapper);
  frappe.pages["overseas-cost-workbench"].workbench = workbench;
  workbench.init();
};

frappe.pages["overseas-cost-workbench"].on_page_show = function () {
  const workbench = frappe.pages["overseas-cost-workbench"].workbench;
  if (!workbench) return;
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
      customs_no: "",
      waybill_no: "",
      material_code: "",
      product_name: "",
      import_name: "",
      hs_code: "",
      category: "",
      transport_mode: "",
    };
    this.readonlyCalcFields = new Set(["goods_value_ratio", "freight_alloc_rmb", "freight_alloc_mxn", "total_logistics_mxn"]);
    this.specialOverrideFields = new Set(["weight_ratio", "alloc_price_mxn", "total_cost_rmb", "total_unit_rmb"]);
    this.selectOptions = {
      transport_mode: ["SEA", "AIR", "EXPRESS"],
      purchase_currency: ["RMB", "USD", "MXN"],
    };
    this.auditEvents = [];
    this.lastImportResult = null;
    this.lastRecalculateResult = null;
    this.lastImportedBatchNames = new Set();
    this.isOpeningDingtalk = false;
    this.isParsingManualDocuments = false;
    this.defaultRecentDays = 30;
  }

  init() {
    this.page = frappe.ui.make_app_page({
      parent: this.wrapper,
      title: "海外采购综合成本核算",
      single_column: true,
    });
    this.applyDeskLayout();
    this.addActions();
    this.renderShell();
    this.bindEvents();
    this.loadBatches();
  }

  applyDeskLayout() {
    const $wrapper = $(this.wrapper);
    const $pageContainer = $wrapper.closest(".page-container");
    const $scope = $pageContainer.length ? $pageContainer : $wrapper;
    const $mainSection = $(this.page.main);

    $scope.addClass("ocw-desk-fullwidth");
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

    $scope
      .find(
        ".page-head .container, .page-body, .page-body > .container, .page-content, .page-wrapper, .layout-main, .layout-main-section, .layout-main-section-wrapper"
      )
      .addClass("ocw-desk-wide-node");
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
                <span>运输方式</span>
                <button class="ocw-text-btn" type="button" data-action="set-transport-filter" data-transport-mode="">全部</button>
              </div>
              <div class="ocw-logistics-list" data-area="transport-workbench"></div>
            </section>
          </aside>

          <main class="ocw-main">
            <section class="ocw-workbench-card">
              <div class="ocw-workbench-head">
                <div>
                  <h3>SKU 成本分摊明细 / 物料详情</h3>
                  <p>父级行展示报关单号、运单号、运费汇总；展开后按 Excel A~BE 原列顺序查看 SKU 明细。</p>
                </div>
                <div class="ocw-head-actions">
                  <span class="ocw-summary-pill" data-area="hierarchy-summary">加载批次中</span>
                  <button class="ocw-outline-btn ocw-mini-btn" data-action="file-parse">文件解析</button>
                  <button class="ocw-outline-btn ocw-mini-btn" data-action="preview-categories">商品归类</button>
                  <button class="ocw-outline-btn ocw-mini-btn" data-action="open-import">Excel 导入</button>
                  <button class="ocw-outline-btn ocw-mini-btn" data-action="export-current">导出当前结果</button>
                  <button class="ocw-primary-btn ocw-mini-btn" data-action="add-batch">+ 添加报关运单</button>
                </div>
              </div>

              <div class="ocw-query-toolbar">
                <div class="ocw-filter-grid">
                  <label class="ocw-toolbar-field">
                    <span>报关单号</span>
                    <input data-filter="customs_no" class="form-control" type="search" placeholder="请输入报关单号" />
                  </label>
                  <label class="ocw-toolbar-field">
                    <span>运单号</span>
                    <input data-filter="waybill_no" class="form-control" type="search" placeholder="请输入运单号" />
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
                  <div class="ocw-filter-actions">
                    <button class="ocw-primary-btn ocw-mini-btn" data-action="apply-filters">查询</button>
                    <button class="ocw-outline-btn ocw-mini-btn" data-action="clear-filters">重置</button>
                  </div>
                </div>
                <div class="ocw-search-result" data-area="search-result">所有输入框均为可选，可单独或组合查询</div>
              </div>

              <div class="ocw-table-toolbar">
                <div class="ocw-table-toolbar-left">
                  <button class="ocw-outline-btn ocw-mini-btn" data-action="clear-batch-focus" hidden>返回全部批次</button>
                  <button class="ocw-outline-btn ocw-mini-btn" data-action="expand-current">+ 全部展开</button>
                  <button class="ocw-outline-btn ocw-mini-btn" data-action="collapse-current">- 全部收起</button>
                  <strong data-area="table-title">明细</strong>
                  <span data-area="table-count"></span>
                </div>
                <div class="ocw-table-actions"></div>
              </div>
              <div class="ocw-hierarchy-wrap" data-area="table"></div>
            </section>

            <div class="ocw-batch-drawer-mask" data-area="batch-drawer-mask" data-action="close-batch-drawer"></div>
            <aside class="ocw-batch-drawer" data-area="batch-drawer" aria-hidden="true">
              <div class="ocw-batch-drawer-head">
                <div>
                  <span>批次详情</span>
                  <strong data-area="batch-drawer-title">双击批次查看详情</strong>
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
                <button class="ocw-batch-drawer-tab" data-action="switch-batch-drawer-tab" data-tab="audit">修改记录</button>
                <button class="ocw-batch-drawer-tab" data-action="switch-batch-drawer-tab" data-tab="allocation">AI 分摊</button>
              </div>
              <div class="ocw-batch-drawer-body" data-area="batch-drawer-body"></div>
            </aside>

          </main>
        </div>
      </div>
    `);
    $(this.page.main).empty().append(this.$root);
    this.applyDeskLayout();
    this.renderEmpty();
    this.renderAuditList();
    this.renderDiffPanel();
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
    this.$root.on("click", "[data-action='apply-filters']", () => this.applyFilters());
    this.$root.on("click", "[data-action='clear-filters']", () => this.clearFilters());
    this.$root.on("click", "[data-action='set-transport-filter']", (event) =>
      this.setTransportFilter($(event.currentTarget).attr("data-transport-mode")).catch((error) => this.showError(error))
    );
    this.$root.on("click", "[data-action='recalculate']", (event) => this.recalculate($(event.currentTarget).attr("data-batch-name")));
    this.$root.on("click", "[data-action='open-import']", () => this.openImportDialog());
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
    this.$root.on("click", "[data-action='export-drawer-batch']", () => this.exportDrawerBatch().catch((error) => this.showError(error)));
    this.$root.on("click", "[data-action='open-batch-drawer-dingtalk']", () => this.openDingtalkOrder(this.drawerBatchName));
    this.$root.on("click", "[data-action='open-batch-drawer-recalculate']", () => this.recalculate(this.drawerBatchName));
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

    this.$root.on("input", "input[data-filter]", (event) => {
      const field = $(event.currentTarget).attr("data-filter");
      this.filters[field] = $(event.currentTarget).val();
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
      const urlBatchKey = this.getBatchNameFromUrl();
      const result = await this.call("overseas_costing.api.batch.get_batch_list", {
        transport_mode: "",
        recent_days: this.defaultRecentDays,
        keyword: urlBatchKey || "",
      });
      this.batches = result.items || [];
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

  async applyFilters() {
    this.setTableLoading();
    try {
      this.focusedBatchName = "";
      this.closeBatchDrawer({ updateUrl: false });
      this.updateBatchUrl("", { replace: true });
      this.exportPinnedBatchName = "";
      this.batchItems = {};
      const searchedServer = await this.reloadBatchesForServerSearch();
      if (!this.batches.length && !searchedServer) {
        await this.loadBatches();
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

  getServerSearchKeyword() {
    return [this.filters.customs_no, this.filters.waybill_no]
      .map((value) => String(value || "").trim())
      .find(Boolean) || "";
  }

  async reloadBatchesForServerSearch() {
    const keyword = this.getServerSearchKeyword();
    if (!keyword) return false;
    const result = await this.call("overseas_costing.api.batch.get_batch_list", {
      transport_mode: "",
      recent_days: this.defaultRecentDays,
      keyword,
    });
    this.batches = result.items || [];
    this.visibleBatches = this.batches.slice();
    return true;
  }

  clearFilters() {
    this.resetFilterValues();
    this.batchItems = {};
    this.loadBatches();
  }

  async setTransportFilter(mode = "") {
    this.filters.transport_mode = this.normalizeTransportMode(mode);
    this.focusedBatchName = "";
    this.closeBatchDrawer({ updateUrl: false });
    this.updateBatchUrl("", { replace: true });
    this.exportPinnedBatchName = "";
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

  resetFilterValues() {
    Object.keys(this.filters).forEach((key) => {
      this.filters[key] = "";
      this.$root.find(`[data-filter='${key}']`).val("");
    });
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
      frappe.show_alert({ message: result.message || "重新试算完成", indicator: summary.ai_allocation?.ok ? "green" : "orange" });
    } catch (error) {
      this.showError(error);
    }
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
        this.renderBatchDrawer();
      }
    } catch (error) {
      this.showError(error);
    }
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
      title: "文件解析预览",
      fields: [
        {
          fieldtype: "HTML",
          fieldname: "file_parse",
          options: `
            <div class="ocw-file-parse-box">
              <div class="ocw-voucher-target">
                <label class="ocw-voucher-batch-picker">
                  <span>解析对比批次</span>
                  <select class="form-control ocw-batch-select" data-role="voucher-batch-select" aria-label="选择文件解析批次"${batchSelectDisabled}>${batchOptions}</select>
                </label>
                <em data-area="voucher-batch-hint">${this.escape(batchHint)}</em>
              </div>
              <label class="ocw-import-file-label">上传完税凭证 PDF</label>
              <div class="ocw-import-dropzone" data-voucher-dropzone="1" tabindex="0">
                <input class="ocw-voucher-file-input" type="file" accept=".pdf" />
                <div class="ocw-import-drop-icon">PDF</div>
                <div>
                  <strong data-area="voucher-file-name">拖放 PDF 到这里，或点击选择</strong>
                  <span>当前仅做完税凭证解析预览，不写入成本表。</span>
                </div>
              </div>
              <div class="ocw-import-preview-actions">
                <button class="ocw-outline-btn ocw-mini-btn" type="button" data-action="preview-voucher">解析预览</button>
                <span data-area="voucher-preview-status">选择文件后可先预览凭证字段。</span>
              </div>
              <div class="ocw-voucher-preview empty" data-area="voucher-preview">尚未解析</div>
              <div class="ocw-voucher-records">
                <div class="ocw-voucher-records-head">
                  <strong>已保存解析记录</strong>
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
      primary_action_label: "保存解析结果",
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
      frappe.msgprint("请先点击「解析预览」，确认凭证已匹配到系统批次后再保存。");
      return;
    }
    const canSave = Boolean(preview.reconciliation && preview.reconciliation.batch && preview.reconciliation.batch.name);
    if (!canSave) {
      frappe.msgprint("当前凭证还没有匹配到系统批次，暂不能保存解析结果。");
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
      frappe.msgprint((result && result.message) || "保存解析结果失败。");
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
      frappe.msgprint("当前列表没有可删除的解析记录。");
      return;
    }
    frappe.confirm(
      `确认删除当前列表显示的 ${recordCount} 条完税凭证解析记录？删除后只移除解析记录，不会删除批次和物料明细。`,
      async () => {
        const result = await this.call(
          "overseas_costing.api.import_api.delete_tax_certificate_parse_records",
          { record_names_json: JSON.stringify(targetNames) },
          true
        );
        if (!result || !result.ok) {
          frappe.msgprint((result && result.message) || "删除解析记录失败。");
          return;
        }
        frappe.show_alert({ message: result.message || "解析记录已删除。", indicator: "green" });
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
      frappe.msgprint((result && result.message) || "未能读取完税凭证解析记录。");
      return;
    }

    const detailDialog = new frappe.ui.Dialog({
      title: "完税凭证解析记录",
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
      $status.text("选择文件后可先预览凭证字段。");
      $preview.addClass("empty").text("尚未解析");
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

  updateVoucherPrimarySaveAction(dialog, canSave, label = "保存解析结果") {
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
        ? `<button class="ocw-primary-btn ocw-mini-btn" type="button" data-action="save-voucher-parse">${reconciliation.saved_attachment_name ? "已保存解析结果" : "保存解析结果"}</button>`
        : `<button class="ocw-primary-btn ocw-mini-btn" type="button" data-action="save-voucher-parse" disabled>保存解析结果</button>`;

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
    if (data.message && typeof data.message === "string") return data.message;
    if (data._server_messages) {
      try {
        const messages = JSON.parse(data._server_messages).map((item) => JSON.parse(item).message || item);
        return messages.join("；");
      } catch (_error) {
        return String(data._server_messages);
      }
    }
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
              <th>规格型号</th>
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
            const meta = `${row.purchase_currency || "--"} · ${row.detail_row_count || 0} 行`;
            const button = row.can_open
              ? `<a class="ocw-link-btn" href="${this.escape(row.open_url || "")}" target="_blank" rel="noopener noreferrer">打开原单</a>`
              : `<span class="ocw-purchase-source-disabled">无链接</span>`;
            return `
              <div class="ocw-purchase-source-row">
                <div>
                  <strong>${this.escape(approvalNo)}</strong>
                  <span title="${this.escape(title)}">${this.escape(title)}</span>
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

  openSourceCenterDialog(batchName = "") {
    const batch = batchName ? this.findBatch(batchName) : this.getActiveBatch();
    if (!batch) {
      this.showPendingFeature("当前没有可查看资料的批次。");
      return;
    }
    this.activeBatchName = batch.name;
    const logisticsType = this.detectManualDocumentLogisticsType(batch);
    const dialog = new frappe.ui.Dialog({
      title: "资料上传与补齐",
      size: "large",
      fields: [
        {
          fieldtype: "HTML",
          fieldname: "manual_documents",
          options: `<div data-area="manual-documents">${this.renderManualDocumentPanel(batch, logisticsType, [])}</div>`,
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
        this.loadManualDocumentAttachments(batch, dialog, nextType).catch((error) => this.showError(error));
      })
      .on("click.ocwManualDocuments", "[data-action='upload-manual-document']", (event) => {
        const $button = $(event.currentTarget);
        const slot = {
          code: $button.attr("data-slot-code"),
          label: $button.attr("data-slot-label"),
          attachmentType: $button.attr("data-attachment-type"),
          required: $button.attr("data-required") === "1",
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
        this.deleteManualDocumentAttachment(
          batch,
          dialog,
          $(event.currentTarget).attr("data-attachment-name"),
          $(event.currentTarget).attr("data-logistics-type")
        ).catch((error) => this.showError(error));
      });
    this.loadManualDocumentAttachments(batch, dialog, logisticsType).catch((error) => this.showError(error));
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

  renderManualDocumentPanel(batch, logisticsType = "SEA", items = []) {
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
        <div class="ocw-manual-doc-grid">
          ${this.renderManualDocumentCards(plan, bySlot, logisticsType, batch)}
        </div>
      </div>
    `;
  }

  renderManualDocumentCards(plan = [], bySlot = {}, logisticsType = "SEA", batch = {}) {
    return plan
      .map((slot) => {
        const attachment = bySlot[slot.code] || null;
        const status = this.manualDocumentStatusInfo(slot, attachment, batch);
        const badge = this.manualDocumentBadgeInfo(slot);
        const fileName = attachment ? attachment.file_name || attachment.file_url || "--" : "";
        return `
          <div class="ocw-manual-doc-card ${this.escape(status.className)} ${attachment ? "uploaded" : ""}">
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

  async loadManualDocumentAttachments(batch, dialog, logisticsType = "SEA") {
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
    $target.html(this.renderManualDocumentPanel(batch, logisticsType, result.items || []));
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
    await this.loadManualDocumentAttachments(batch, dialog, logisticsType);
  }

  async deleteManualDocumentAttachment(batch, dialog, attachmentName = "", logisticsType = "SEA") {
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
    await this.loadManualDocumentAttachments(batch, dialog, logisticsType);
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
      ? `<div class="ocw-purchase-apply"><div><strong>当前已确认</strong><span>${this.escape(confirmed.carrier || "未标注供应商")} ${this.escape(`${this.formatNumber(confirmed.amount)} ${confirmed.currency || "RMB"}`)}，已作为整票物流费用参与试算。</span></div></div>`
      : '<div class="ocw-purchase-note">候选报价仅用于辅助确认；未确认前不会写入费用分摊或综合成本。</div>';
    const dialog = new frappe.ui.Dialog({
      title: "物流报价确认",
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
    const stats = this.transportWorkbenchStats();
    const activeMode = this.normalizeTransportMode(this.filters.transport_mode);
    const totalCount = (this.batches || []).length;
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
      { value: "SEA", label: "海运", tip: "主线核算" },
      { value: "AIR", label: "空运", tip: "运单与计费重量" },
      { value: "EXPRESS", label: "快递", tip: "面单与费用补齐" },
    ];
  }

  transportWorkbenchStats() {
    const stats = this.transportWorkbenchModes().reduce((map, mode) => {
      map[mode.value] = { batchCount: 0, itemCount: 0 };
      return map;
    }, {});
    (this.batches || []).forEach((batch) => {
      const mode = this.batchTransportMode(batch);
      if (!stats[mode]) return;
      stats[mode].batchCount += 1;
      stats[mode].itemCount += Number(batch.item_count || (this.batchItems[batch.name] || []).length || 0);
    });
    return stats;
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
    const labels = this.parentTableLabels();
    const displayBatches = this.getDisplayedBatches();
    this.$root.find("[data-area='table-title']").text(labels.title);
    this.$root.find("[data-area='table-count']").text(`${displayBatches.length} 个${labels.blockName}`);
    this.renderBatchFocusControls();
    this.updateHierarchySummary();

    if (!displayBatches.length) {
      this.$root.find("[data-area='table']").html(`<div class="ocw-muted ocw-table-empty">暂无匹配的报关/来源单块</div>`);
      return;
    }

    const rows = displayBatches.map((batch) => this.renderBatchRows(batch)).join("");
    this.$root.find("[data-area='table']").html(`
      <table class="ocw-hierarchy-table">
        <colgroup>
          <col class="ocw-col-toggle" />
          <col class="ocw-col-customs" />
          <col class="ocw-col-waybill" />
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
            <th>${this.escape(labels.sourceNo)}</th>
            <th>${this.escape(labels.logisticsNo)}</th>
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

  parentTableLabels() {
    const mode = this.normalizeTransportMode(this.filters.transport_mode);
    const defaults = {
      title: "报关/来源单层级列表",
      sourceNo: "报关/来源单号",
      logisticsNo: "运单/物流单号",
      blockName: "报关/来源单块",
    };
    const byMode = {
      SEA: {
        title: "海运报关/来源单层级列表",
        sourceNo: "报关/来源单号",
        logisticsNo: "运单/柜号",
        blockName: "海运单块",
      },
      AIR: {
        title: "空运来源单层级列表",
        sourceNo: "来源单号",
        logisticsNo: "空运运单号",
        blockName: "空运单块",
      },
      EXPRESS: {
        title: "快递来源单层级列表",
        sourceNo: "来源单号",
        logisticsNo: "快递运单号",
        blockName: "快递单块",
      },
    };
    return byMode[mode] || defaults;
  }

  renderBatchRows(batch) {
    const isExpanded = this.expandedBatchNames.has(batch.name);
    return this.renderParentRow(batch, isExpanded) + (isExpanded ? this.renderChildRow(batch) : "");
  }

  renderParentRow(batch, isExpanded) {
    const items = this.batchItems[batch.name] || [];
    const hasLoadedItems = Object.prototype.hasOwnProperty.call(this.batchItems, batch.name);
    const firstItem = items[0] || {};
    const sourceRange = this.sourceLabel(batch, firstItem);
    const customsNo = batch.customs_no || firstItem.customs_no || batch.batch_no || firstItem.source_doc_no || "--";
    const waybillNo = batch.waybill_no || firstItem.waybill_no || "--";
    const itemCount = hasLoadedItems ? items.length : batch.item_count || 0;
    const statusInfo = this.batchStatusInfo(batch.status, batch, itemCount);
    const documentStatus = this.batchDocumentStatus(batch, items, hasLoadedItems);
    const goodsValueDisplay = this.batchGoodsValueDisplay(batch, items, hasLoadedItems);
    const recognizedFeeDisplay = this.batchRecognizedFeeDisplay(batch, items, hasLoadedItems);
    const totalCostDisplay = this.batchTotalCostDisplay(batch, items, hasLoadedItems);
    const voucherDiffDisplay = this.batchVoucherDiffDisplay(batch);
    const importedClass = this.lastImportedBatchNames.has(batch.name) ? "imported" : "";
    this.activeBatchName = this.activeBatchName || batch.name;
    return `
      <tr class="ocw-parent-row ${isExpanded ? "expanded" : ""} ${importedClass}" data-batch-name="${this.escape(batch.name)}" title="双击查看批次详情">
        <td>
          <button class="ocw-tree-toggle" data-action="toggle-batch" data-batch-name="${this.escape(batch.name)}" aria-expanded="${isExpanded ? "true" : "false"}">
            ${isExpanded ? "-" : "+"}
          </button>
        </td>
        <td title="${this.escape(this.formatValue(customsNo || ""))}">
          <strong>${this.renderParentValue(customsNo, "customs_no")}</strong>
          <small>${this.escape(sourceRange)}</small>
          <span class="ocw-status ${this.escape(this.statusClass(batch.status))}">${this.escape(statusInfo.label)}</span>
        </td>
        <td title="${this.escape(this.formatValue(waybillNo || ""))}">
          <strong>${this.renderParentValue(waybillNo, "waybill_no")}</strong>
          <small>${this.escape(this.transportLabel(batch.transport_mode || firstItem.transport_mode))}</small>
        </td>
        <td class="ocw-num-cell">${this.escape(String(itemCount))}</td>
        <td>${this.renderParentMetric(documentStatus)}</td>
        <td>${this.renderParentMetric(goodsValueDisplay)}</td>
        <td>${this.renderParentMetric(recognizedFeeDisplay)}</td>
        <td>${this.renderParentMetric(totalCostDisplay)}</td>
        <td>${this.renderParentMetric(voucherDiffDisplay)}</td>
        <td class="ocw-row-actions">
          <div class="ocw-row-action-group">
            <button class="ocw-outline-btn ocw-mini-btn" data-action="recalculate" data-batch-name="${this.escape(batch.name)}">重新试算</button>
            <button class="ocw-outline-btn ocw-mini-btn" data-action="source-center" data-batch-name="${this.escape(batch.name)}">资料</button>
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

  batchDocumentStatus(batch, items, hasLoadedItems) {
    const sourceStatus = batch.source_status || {};
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
      value: taxCertificateCount ? "资料较全" : "资料可用",
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
      return { value: "待补货值", hint: "缺采购单价或金额", className: "warn" };
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
          .map(
            (row) => `
              <div class="ocw-allocation-row">
                <div>
                  <strong>${this.escape(row.amountTitle)}</strong>
                  <span>${this.escape(row.amountText)}</span>
                </div>
                <div title="${this.escape(row.source)}">${this.escape(row.source)}</div>
                <div>${this.escape(row.basis)}</div>
                <div>${this.escape(row.result)}</div>
              </div>
            `
          )
          .join("")
      : `
        <div class="ocw-allocation-empty">
          暂无可填入的费用分摊金额。请先确认物流费、清关费、税费或杂费，然后点击“重新试算”填入 AI/系统基础分摊金额。
        </div>
      `;

    return `
      <div class="ocw-allocation-overview">
        <div class="ocw-allocation-title">
          <strong>AI/系统基础分摊填入</strong>
          <span>费用池金额 + 费用来源 + 分摊依据 + 分摊结果</span>
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
    const amountParts = [];
    if (bucket.amount !== null && bucket.amount !== undefined) {
      amountParts.push(`${this.formatNumber(bucket.amount)} ${bucket.currency || "RMB"}`);
      if (bucket.currency !== "RMB" && this.isPositive(bucket.amountRmb)) {
        amountParts.push(`折 ${this.formatNumber(bucket.amountRmb)} RMB`);
      }
    } else if (this.isPositive(bucket.allocatedRmb)) {
      amountParts.push(`${this.formatNumber(bucket.allocatedRmb)} RMB（按分摊汇总）`);
    } else if (this.isPositive(bucket.allocatedMxn)) {
      amountParts.push(`${this.formatNumber(bucket.allocatedMxn)} MXN（按分摊汇总）`);
    } else {
      amountParts.push("--");
    }

    const resultParts = [];
    if (this.isPositive(bucket.allocatedRmb)) resultParts.push(`${this.formatNumber(bucket.allocatedRmb)} RMB`);
    if (this.isPositive(bucket.allocatedMxn)) resultParts.push(`${this.formatNumber(bucket.allocatedMxn)} MXN`);
    const coveredCount = bucket.coveredRows && bucket.coveredRows.size ? bucket.coveredRows.size : 0;
    if (coveredCount) resultParts.push(`覆盖 ${coveredCount} 行`);

    return {
      amountTitle: bucket.feeName || "费用池",
      amountText: amountParts.join(" / "),
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
      amountText: amountParts.join(" / "),
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
        <td colspan="10">
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

  sourceLabel(batch, firstItem = {}) {
    const explicit = firstItem.source_range || firstItem.source_sheet || batch.source_range || batch.source_sheet;
    if (this.hasText(explicit)) return explicit;
    if (batch.source_type === "oa_logistics" || firstItem.source_type === "oa_logistics") {
      const itemCount = Number(batch.item_count || 0);
      return itemCount ? "钉钉国际物流 OA" : "钉钉国际物流 OA · 待解析附件";
    }
    const transportMode = String(batch.transport_mode || firstItem.transport_mode || "").toUpperCase();
    const looksLikeLegacyYuewei =
      transportMode === "SEA" ||
      this.hasText(batch.customs_no) ||
      this.hasText(firstItem.customs_no) ||
      this.hasText(batch.waybill_no) ||
      this.hasText(firstItem.waybill_no);
    if (looksLikeLegacyYuewei) return "2026年YUEWEI";
    return "来源工作表待识别";
  }

  renderChildTable(batch) {
    const columns = this.batchColumns || [];
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
            const rawValue = this.normalizeEditorValue(row[column.fieldname]);
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
    if (value === null || value === undefined || value === "") {
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
    const allowedTabs = new Set(["overview", "audit", "allocation"]);
    this.drawerTab = allowedTabs.has(tab) ? tab : "overview";
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
    if (this.drawerTab === "allocation") {
      return this.renderBatchDrawerAllocation(batch, items);
    }
    return this.renderBatchDrawerOverview(batch, items);
  }

  renderBatchDrawerOverview(batch, items) {
    const sourceStatus = batch.source_status || {};
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
      ["状态", this.batchStatusInfo(batch.status, batch, itemCount).label],
      ["物料行数", itemCount],
      ["采购货值", `${this.formatNumber(goodsValue)} RMB`],
      ["综合成本", `${this.formatNumber(totalCost || summary.total_cost_rmb)} RMB`],
      ["资料情况", this.sourceStatusLabel(sourceStatus, batch)],
    ];
    const previewRows = items.slice(0, 8).map((item, index) => `
      <tr>
        <td>${this.escape(String(index + 1))}</td>
        <td>${this.escape(this.formatValue(item.material_code || "--"))}</td>
        <td>${this.escape(this.formatValue(item.product_name || item.product_name_es || "--"))}</td>
        <td>${this.escape(this.formatValue(item.quantity))}</td>
        <td>${this.escape(this.formatValue(item.unit_price))}</td>
        <td>${this.escape(this.formatValue(item.purchase_currency || "--"))}</td>
      </tr>
    `).join("");
    return `
      <div class="ocw-batch-drawer-section">
        <div class="ocw-batch-drawer-field-grid">
          ${fields.map(([label, value]) => `<div><span>${this.escape(label)}</span><strong>${this.escape(this.formatValue(value))}</strong></div>`).join("")}
        </div>
      </div>
      <div class="ocw-batch-drawer-section">
        <div class="ocw-batch-drawer-section-head"><h4>物料明细预览</h4><span>${items.length > 8 ? `显示前 8 行，共 ${items.length} 行` : `${items.length} 行`}</span></div>
        ${previewRows ? `
          <div class="ocw-batch-drawer-table-wrap"><table class="ocw-batch-drawer-table"><thead><tr><th>#</th><th>物料编码</th><th>物料名称</th><th>数量</th><th>单价</th><th>币种</th></tr></thead><tbody>${previewRows}</tbody></table></div>
        ` : `<div class="ocw-batch-drawer-empty"><span>当前批次暂无物料明细</span></div>`}
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

  sourceStatusLabel(sourceStatus, batch) {
    if (Number(sourceStatus.oa_attachment_count || batch.source_attachment_count || 0) > 0) return "已有关联资料";
    if (batch.source_approval_no || batch.source_instance_id || batch.source_dingtalk_url) return "已关联钉钉审批单";
    return "待补资料";
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
    $result.removeClass("imported calculated");
    if (!this.hasActiveFilters()) {
      $result.removeClass("active empty").text("所有输入框均为可选，可单独或组合查询");
      return;
    }
    const modeLabel = this.filters.transport_mode ? `${this.transportLabel(this.filters.transport_mode)} · ` : "";
    if (this.visibleBatches.length) {
      $result
        .removeClass("empty")
        .addClass("active")
        .text(`${modeLabel}筛出 ${this.visibleBatches.length} 个报关/运单块 · 共 ${this.countVisibleItems()} 行 SKU（已自动展开）`);
    } else {
      $result.removeClass("active").addClass("empty").text(`${modeLabel}未找到匹配的报关/运单块`);
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
    const displayBatches = this.getDisplayedBatches();
    const batchCount = displayBatches.length;
    if (this.focusedBatchName && displayBatches.length) {
      const batch = displayBatches[0];
      this.$root
        .find("[data-area='hierarchy-summary']")
        .text(`当前批次：${this.batchReferenceLabel(batch)} · 已展开物料明细`);
      return;
    }
    const modeLabel = this.filters.transport_mode ? `${this.transportLabel(this.filters.transport_mode)} · ` : "";
    const label = this.hasActiveFilters()
      ? `${modeLabel}筛出 ${batchCount} 个报关/运单块 · 点击 + 展开 SKU 明细`
      : `${batchCount} 个报关/运单块 · 点击 + 展开 SKU 明细`;
    this.$root.find("[data-area='hierarchy-summary']").text(label);
  }

  getDisplayedBatches() {
    if (!this.focusedBatchName) return this.visibleBatches;
    const focusedBatch = this.visibleBatches.find((batch) => batch.name === this.focusedBatchName);
    return focusedBatch ? [focusedBatch] : this.visibleBatches;
  }

  renderBatchFocusControls() {
    const isFocused = Boolean(this.focusedBatchName && this.getDisplayedBatches().length === 1);
    this.$root.find("[data-action='clear-batch-focus']").prop("hidden", !isFocused);
    this.$root.find("[data-action='expand-current'], [data-action='collapse-current']").prop("hidden", isFocused);
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
    const column = (this.batchColumns || []).find((item) => item.fieldname === fieldName);
    return column ? column.label : fieldName;
  }

  formatAuditChangeValue(fieldName, value) {
    if (fieldName !== "item") return value;
    if (value === null || value === undefined || value === "") return "";
    const parsed = this.tryParseJson(value);
    if (!parsed || typeof parsed !== "object") return value;
    const code = parsed.material_code || parsed.name || "";
    const name = parsed.product_name || "";
    const quantity = parsed.quantity !== undefined && parsed.quantity !== "" ? `，数量 ${parsed.quantity}` : "";
    const goodsValue = parsed.goods_value !== undefined && parsed.goods_value !== "" ? `，货值 ${parsed.goods_value}` : "";
    const label = [code, name].filter(Boolean).join(" / ");
    return `${label || "未命名物料"}${quantity}${goodsValue}`;
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
        ? `${reviewIssues.join("，")}；财务可双击明细补齐后重新试算`
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
          ? `${reviewIssues.join("，")}；财务可双击明细补齐后重新试算`
          : "基础分摊金额已填入明细；后续可双击人工修改，税费最终以完税凭证对账为准",
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

  async focusBatch(batchName, options = {}) {
    if (!batchName) return;
    const batch = this.findBatch(batchName);
    if (!batch) return;
    this.activeBatchName = batch.name;
    this.exportPinnedBatchName = batch.name;
    this.dataCheckBatchName = batch.name;
    this.focusedBatchName = batch.name;
    await Promise.all([
      this.loadBatchItems(batch.name, batch.current_version),
      this.loadAuditLogs(batch.name, batch.current_version),
    ]);
    this.expandedBatchNames = new Set([batch.name]);
    this.renderTable();
    this.renderDiffPanel();
    if (options.updateUrl !== false) this.updateBatchUrl(this.batchUrlKey(batch), { view: "" });
  }

  clearBatchFocus(options = {}) {
    const hadFocus = Boolean(this.focusedBatchName);
    this.focusedBatchName = "";
    this.expandedBatchNames.clear();
    this.closeBatchDrawer({ updateUrl: false });
    if (hadFocus) {
      this.renderTable();
      this.updateSearchResult();
    }
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
    if (expanded) {
      await this.prefetchBatchItems(this.visibleBatches);
      this.expandedBatchNames = new Set(this.visibleBatches.map((batch) => batch.name));
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
        { fieldtype: "Data", fieldname: "spec_model", label: "规格型号" },
        { fieldtype: "Float", fieldname: "unit_price", label: "单价", default: 0 },
        { fieldtype: "Float", fieldname: "quantity", label: "数量", default: 1 },
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
    return Object.keys(this.filters).some((key) => String(this.filters[key] || "").trim() !== "");
  }

  filterBatches() {
    const customs = this.lower(this.filters.customs_no);
    const waybill = this.lower(this.filters.waybill_no);
    const transportMode = this.normalizeTransportMode(this.filters.transport_mode);
    const itemFilters = ["material_code", "product_name", "import_name", "hs_code", "category"];
    return this.batches.filter((batch) => {
      const items = this.batchItems[batch.name] || [];
      if (transportMode && this.batchTransportMode(batch, items) !== transportMode) return false;
      const customsMatched = !customs || this.batchMatchesQuery(batch, items, customs, [
        "customs_no",
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
    });
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
      ? "仅显示当前筛选范围内的批次；输入报关单号/运单号可查询历史批次。"
      : `默认显示最近 ${this.defaultRecentDays} 天批次；输入报关单号/运单号可查询历史批次。`;
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
    if (["import_name", "product_name"].includes(column.fieldname)) return "ocw-col-long";
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

  formatCellValue(value, column) {
    if (column.fieldname === "transport_mode") return this.transportLabel(value);
    if (column.fieldname === "purchase_currency") return this.currencyLabel(value);
    if (this.isNumericField(column.fieldname)) return this.formatNumber(value);
    return this.formatValue(value);
  }

  formatValue(value) {
    if (value === null || value === undefined || value === "") return "";
    if (typeof value === "number") return this.formatNumber(value);
    return String(value);
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
    const raw = error && error.message ? error.message : error;
    let message = raw ? String(raw) : "操作失败";
    message = message.replace(/^Server Error\s*/i, "").trim() || "操作失败";
    message = message.replace(/^ValueError:\s*/i, "");
    if (message.includes("工作簿中不存在工作表")) {
      message += "\n\n建议：工作表名称可以留空，由系统自动识别；只有一个工作表的文件会自动使用该工作表。";
    }
    return message;
  }
}
