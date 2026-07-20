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
    this.filters = {
      customs_no: "",
      waybill_no: "",
      material_code: "",
      product_name: "",
      import_name: "",
      hs_code: "",
      category: "",
    };
    this.readonlyCalcFields = new Set(["goods_value_ratio", "freight_alloc_rmb", "freight_alloc_mxn", "total_logistics_mxn"]);
    this.specialOverrideFields = new Set(["weight_ratio", "alloc_price_mxn", "total_cost_rmb", "total_unit_rmb"]);
    this.selectOptions = {
      transport_mode: ["SEA", "AIR", "EXPRESS"],
    };
    this.auditEvents = [];
    this.lastImportResult = null;
    this.lastRecalculateResult = null;
    this.lastImportedBatchNames = new Set();
    this.isOpeningDingtalk = false;
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
            <button class="ocw-sidebar-alert" data-action="show-scope">
              <strong>待确认口径</strong>
              <span>共享费用分摊范围、海运费取数来源待财务确认</span>
            </button>
            <section class="ocw-scope-panel">
              <span>一期范围</span>
              <strong>先跑数据摘取和试算</strong>
              <p>海运成本总表、空运/快递审批附件可先入库；费用口径缺失时后续补数。</p>
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
                  <button class="ocw-outline-btn ocw-mini-btn" data-action="preview-categories">品类归类</button>
                  <button class="ocw-outline-btn ocw-mini-btn" data-action="open-import">Excel 导入</button>
                  <button class="ocw-primary-btn ocw-mini-btn" data-action="recalculate">重新试算</button>
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
                  <button class="ocw-outline-btn ocw-mini-btn" data-action="expand-current">+ 全部展开</button>
                  <button class="ocw-outline-btn ocw-mini-btn" data-action="collapse-current">- 全部收起</button>
                  <strong data-area="table-title">明细</strong>
                  <span data-area="table-count"></span>
                </div>
                <div class="ocw-table-actions"></div>
              </div>
              <div class="ocw-hierarchy-wrap" data-area="table"></div>
            </section>

            <section class="ocw-bottom-grid">
              <article class="ocw-bottom-panel">
                <h2>修改记录</h2>
                <ul class="ocw-audit-list" data-area="audit-list"></ul>
              </article>
              <article class="ocw-bottom-panel">
                <h2>数据检查</h2>
                <div class="ocw-diff-wrap" data-area="diff-panel"></div>
              </article>
            </section>
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
      const batchName = $(event.currentTarget).attr("data-batch-name");
      if (batchName) {
        this.activeBatchName = batchName;
        this.renderDiffPanel();
        this.updateRecalculateAction();
        const batch = this.findBatch(batchName);
        this.loadAuditLogs(batchName, batch ? batch.current_version : null).catch((error) => this.showError(error));
      }
    });

    this.$root.on("click", "[data-action='reload-batches']", () => this.loadBatches());
    this.$root.on("click", "[data-action='apply-filters']", () => this.applyFilters());
    this.$root.on("click", "[data-action='clear-filters']", () => this.clearFilters());
    this.$root.on("click", "[data-action='recalculate']", () => this.recalculate());
    this.$root.on("click", "[data-action='open-import']", () => this.openImportDialog());
    this.$root.on("click", "[data-action='preview-categories']", () => this.openCategoryPreviewDialog());
    this.$root.on("click", "[data-action='file-parse']", () => this.openFileParseDialog());
    this.$root.on("click", "[data-action='show-scope']", () => this.showPendingFeature("当前先支持成本总表和国际物流审批附件 Excel 的数据摘取；费用口径不完整时先落基础明细，后续由钉钉/凭证继续补数。"));
    this.$root.on("click", "[data-action='open-dingtalk']", (event) => this.openDingtalkOrder($(event.currentTarget).attr("data-batch-name")));
    this.$root.on("click", "[data-action='add-batch']", () => this.showPendingFeature("添加报关运单入口已保留，下一步接入新增保存接口。"));
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
    this.$root.on("dblclick", "[data-editable-cell='1']", (event) => this.startCellEdit($(event.currentTarget), event));
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
  }

  async call(method, args = {}, freeze = false) {
    const response = await frappe.call({ method, args, freeze });
    return response.message || {};
  }

  async loadBatches() {
    this.setTableLoading();
    try {
      const result = await this.call("overseas_costing.api.batch.get_batch_list", {
        transport_mode: "",
      });
      this.batches = result.items || [];
      this.visibleBatches = this.batches.slice();
      this.expandedBatchNames.clear();
      await this.prefetchBatchItems(this.visibleBatches);
      if (this.batches.length) {
        if (!this.findBatch(this.activeBatchName)) {
          this.activeBatchName = this.batches[0].name;
        }
        const activeBatch = this.getActiveBatch();
        await this.loadAuditLogs(activeBatch.name, activeBatch.current_version);
        this.renderTable();
        this.updateSearchResult();
        this.updateRecalculateAction();
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
      customs_no: this.filters.customs_no,
      waybill_no: this.filters.waybill_no,
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
    if (!this.batches.length) {
      await this.loadBatches();
      return;
    }
    this.setTableLoading();
    try {
      this.batchItems = {};
      await this.prefetchBatchItems(this.batches);
      this.visibleBatches = this.filterBatches();
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
    this.applyFilters();
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

  async recalculate() {
    const batch = this.getActiveBatch();
    if (!batch) return;
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
      this.applyRecalculateSummary(batch.name, summary);
      await this.loadBatchItems(batch.name, batch.current_version, true);
      await this.loadAuditLogs(batch.name, batch.current_version);
      this.renderTable();
      this.lastRecalculateResult = { batch_name: batch.name, summary };
      this.renderRecalculateResult(batch.name, summary);
      frappe.show_alert({ message: "重新试算完成", indicator: "green" });
    } catch (error) {
      this.showError(error);
    }
  }

  async refreshBatch(batchName) {
    const batch = this.findBatch(batchName);
    if (!batch) return;
    this.activeBatchName = batch.name;
    try {
      await this.loadBatchItems(batch.name, batch.current_version, true);
      await this.loadAuditLogs(batch.name, batch.current_version);
      this.renderTable();
    } catch (error) {
      this.showError(error);
    }
  }

  applyRecalculateSummary(batchName, summary) {
    const batch = this.findBatch(batchName);
    if (!batch) return;
    batch.status = "Calculated";
    if (summary.item_count !== undefined) batch.item_count = summary.item_count;
    if (summary.total_goods_value !== undefined) batch.total_goods_value = summary.total_goods_value;
    if (summary.total_gross_weight_kg !== undefined) batch.total_gross_weight_kg = summary.total_gross_weight_kg;
    if (summary.total_cost_rmb !== undefined) batch.estimated_total_cost_rmb = summary.total_cost_rmb;
  }

  openFileParseDialog() {
    const batch = this.getVisibleActiveBatch() || this.getActiveBatch();
    const batchName = batch ? batch.name : "";
    const batchLabel = batch ? batch.customs_no || batch.waybill_no || batch.batch_no || batch.name : "未选择批次";
    const batchHint = batch ? "解析后优先按凭证报关单号/柜号自动匹配，当前页面批次仅作为兜底。" : "解析后会按凭证报关单号/柜号自动尝试匹配批次。";
    const dialog = new frappe.ui.Dialog({
      title: "文件解析预览",
      fields: [
        {
          fieldtype: "HTML",
          fieldname: "file_parse",
          options: `
            <div class="ocw-file-parse-box">
              <div class="ocw-voucher-target">
                <span>当前对比批次</span>
                <strong>${this.escape(batchLabel)}</strong>
                <em>${this.escape(batchHint)}</em>
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
                <button class="ocw-primary-btn ocw-mini-btn" type="button" data-action="save-voucher-parse" disabled>保存解析结果</button>
                <span data-area="voucher-preview-status">选择文件后可先预览凭证字段。</span>
              </div>
              <div class="ocw-voucher-preview empty" data-area="voucher-preview">尚未解析</div>
            </div>
          `,
        },
      ],
      primary_action_label: "关闭",
      primary_action: () => dialog.hide(),
    });
    dialog.show();
    dialog.$wrapper.addClass("ocw-voucher-modal");
    dialog.$wrapper.data("ocw-voucher-batch-name", batchName);
    this.bindVoucherDropzone(dialog);
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
    dialog.$wrapper.on("click", "[data-action='preview-voucher']", (event) => {
      event.preventDefault();
      this.previewTaxCertificate(dialog).catch((error) => this.showError(error));
    });
    dialog.$wrapper.on("click", "[data-action='save-voucher-parse']", (event) => {
      event.preventDefault();
      this.saveTaxCertificateParseResult(dialog).catch((error) => this.showError(error));
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
    const canSave = Boolean(preview.reconciliation && preview.reconciliation.batch && preview.reconciliation.batch.name);
    if (!canSave) {
      frappe.msgprint("当前凭证还没有匹配到系统批次，暂不能保存解析结果。");
      return;
    }

    const uploaded = await this.ensureVoucherFileUploaded(dialog, file);
    const result = await this.call(
      "overseas_costing.api.import_api.save_tax_certificate_parse_result",
      {
        source_name: uploaded.file_name || file.name,
        file_url: uploaded.file_url,
        batch_name: dialog.$wrapper.data("ocw-voucher-batch-name") || "",
      },
      true
    );
    if (!result || !result.ok) {
      frappe.msgprint((result && result.message) || "保存解析结果失败。");
      return;
    }
    if (result.preview) {
      dialog.$wrapper.data("ocw-voucher-preview", result.preview);
      this.renderVoucherPreview(dialog, result.preview, "ready");
    }
    frappe.show_alert({
      message: result.message || "完税凭证解析结果已保存。",
      indicator: "green",
    });
  }

  renderVoucherPreview(dialog, result, state = "empty") {
    const $preview = dialog.$wrapper.find("[data-area='voucher-preview']");
    const $status = dialog.$wrapper.find("[data-area='voucher-preview-status']");
    const $saveButton = dialog.$wrapper.find("[data-action='save-voucher-parse']");
    $preview.removeClass("empty loading ready warn failed");
    $saveButton.prop("disabled", true).attr("title", "请先解析并匹配到系统批次");
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
    const taxChips = [
      ["DTA", taxes.dta_mxn],
      ["PRV", taxes.prv_mxn],
      ["PRV IVA", taxes.prv_iva_mxn],
      ["IGI/IGE", taxes.igi_mxn],
      ["IVA", taxes.iva_mxn],
    ]
      .map(([label, value]) => `<span>${this.escape(label)} ${this.escape(this.formatNumber(value || 0))}</span>`)
      .join("");
    const rows = items.slice(0, 30).map((row) => this.renderVoucherItemRow(row)).join("");
    const moreText = items.length > 30 ? `<div class="ocw-voucher-more">仅展示前 30 条，共 ${this.escape(String(items.length))} 条。</div>` : "";
    const declaredCount = summary.declared_item_count ?? "--";
    const validationHtml = this.renderVoucherValidation(validation);
    const reconciliation = result.reconciliation || {};
    if (result.saved_attachment_name) reconciliation.saved_attachment_name = result.saved_attachment_name;
    const reconciliationHtml = this.renderVoucherReconciliation(reconciliation);
    const reconciliationText = reconciliation.status_label ? `，对比${reconciliation.status_label}` : "";
    const canSave = Boolean(reconciliation.batch && reconciliation.batch.name);
    $saveButton.prop("disabled", !canSave).attr("title", canSave ? "保存解析快照到附件记录" : "未匹配到系统批次，暂不能保存");

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
        <div><span>支付日期</span><strong>${this.escape(header.payment_date || "--")}</strong></div>
        <div><span>汇率</span><strong>${this.escape(this.formatValue(header.exchange_rate || "--"))}</strong></div>
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

  renderVoucherReconciliation(reconciliation) {
    if (!reconciliation || !Object.keys(reconciliation).length) return "";
    const batch = reconciliation.batch || {};
    const voucher = reconciliation.voucher || {};
    const system = reconciliation.system || {};
    const diff = reconciliation.difference || {};
    const checks = reconciliation.checks || [];
    const status = reconciliation.status || "pending";
    const batchLabel = batch.customs_no || batch.waybill_no || batch.batch_no || batch.container_no || batch.name || "未匹配";
    const declaredCount = voucher.declared_item_count ?? voucher.item_count ?? "--";
    const checkRows = checks.map((check) => this.renderVoucherValidationRow(check)).join("");
    const saveButton = batch.name
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
    if (status === "failed") return "failed";
    if (status === "review") return "warn";
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
        dialog.hide();
        await this.importExcel({
          ...values,
          source_sheet: String(values.source_sheet || "").trim(),
          file: uploaded.file_url ? null : file,
          file_url: uploaded.file_url || null,
          source_name: uploaded.file_name || file.name,
        });
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
    } catch (error) {
      this.showError(error);
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
    const parts = [
      `批次 ${label || "--"}`,
      `SKU ${this.formatValue(summary.item_count || 0)} 行`,
      `总货值 ${this.formatNumber(summary.total_goods_value || 0)} RMB`,
      `毛重 ${this.formatNumber(summary.total_gross_weight_kg || 0)} KG`,
      `综合成本 ${this.formatNumber(summary.total_cost_rmb || 0)} RMB`,
      `规则 ${this.formatValue(summary.rule_count || 0)} 条`,
    ];
    this.$root
      .find("[data-area='search-result']")
      .removeClass("empty imported")
      .addClass("active calculated")
      .text(`试算完成：${parts.join("；")}`);
  }

  async openCategoryPreviewDialog(batchName = "") {
    const batch = batchName ? this.findBatch(batchName) : this.getVisibleActiveBatch();
    if (!batch) {
      this.showPendingFeature("当前没有可归类的批次，请先导入或查询一条数据。");
      return;
    }
    this.activeBatchName = batch.name;

    const dialog = new frappe.ui.Dialog({
      title: "商品品类归类预览",
      fields: [
        {
          fieldtype: "HTML",
          fieldname: "category_preview",
          options: `
            <div class="ocw-category-preview" data-area="category-preview">
              <div class="ocw-category-loading">正在分析当前批次物料...</div>
            </div>
          `,
        },
      ],
      primary_action_label: "关闭",
      primary_action: () => dialog.hide(),
    });
    dialog.show();
    dialog.$wrapper.addClass("ocw-category-modal");

    try {
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
    } catch (error) {
      dialog.hide();
      this.showError(error);
    }
  }

  renderCategoryPreview(dialog, result, batch) {
    const $target = dialog.$wrapper.find("[data-area='category-preview']");
    if (!result || !result.ok) {
      $target.html(`
        <div class="ocw-category-empty">
          <strong>暂时无法生成归类预览</strong>
          <span>${this.escape((result && result.message) || "请确认当前批次已有物料明细。")}</span>
        </div>
      `);
      return;
    }

    const items = result.items || [];
    const summary = result.summary || {};
    const categoryCounts = summary.category_counts || {};
    const countChips = Object.keys(categoryCounts)
      .map((category) => `<span>${this.escape(category)} ${this.escape(String(categoryCounts[category]))}</span>`)
      .join("");
    const rows = items.map((row) => this.renderCategoryPreviewRow(row)).join("");
    const batchLabel = batch.waybill_no || batch.batch_no || batch.name;

    $target.html(`
      <div class="ocw-category-summary">
        <div><span>当前批次</span><strong>${this.escape(batchLabel || "--")}</strong></div>
        <div><span>物料行数</span><strong>${this.escape(String(summary.item_count || items.length || 0))}</strong></div>
        <div><span>需复核</span><strong>${this.escape(String(summary.needs_review_count || 0))}</strong></div>
        <div><span>待 AI 判断</span><strong>${this.escape(String(summary.ai_ready_count || 0))}</strong></div>
      </div>
      <div class="ocw-category-note">
        当前仅生成建议，不自动写入“大类分类”，后续接入 AI 后仍保留人工复核。
      </div>
      <div class="ocw-category-counts">${countChips || "<span>暂无建议品类</span>"}</div>
      <div class="ocw-category-table-wrap">
        <table class="ocw-category-table">
          <thead>
            <tr>
              <th>物料编码</th>
              <th>中文品名</th>
              <th>海关进口名称</th>
              <th>海关分类编码</th>
              <th>当前大类</th>
              <th>建议品类</th>
              <th>置信度</th>
              <th>状态</th>
              <th>原因</th>
            </tr>
          </thead>
          <tbody>${rows || `<tr><td colspan="9">当前批次暂无物料明细</td></tr>`}</tbody>
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
        <td>${this.escape(row.hs_code || "--")}</td>
        <td>${this.escape(row.current_category || "--")}</td>
        <td><strong>${this.escape(row.suggested_category || "--")}</strong></td>
        <td>${this.escape(this.formatConfidence(row.confidence))}</td>
        <td><span class="ocw-category-status ${this.escape(status.className)}">${this.escape(status.label)}</span></td>
        <td title="${this.escape(row.reason || "")}">${this.escape(row.reason || "--")}</td>
      </tr>
    `;
  }

  categoryStatusInfo(row) {
    if (row.ai_ready) {
      return { label: "待 AI 判断", className: "ai", rowClass: "needs-ai" };
    }
    if (row.needs_review) {
      return { label: "需复核", className: "review", rowClass: "needs-review" };
    }
    return { label: "可采用", className: "ok", rowClass: "" };
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

  async openDingtalkOrder(batchName = "") {
    const batch = batchName ? this.findBatch(batchName) : this.getActiveBatch();
    if (!batch) {
      this.showPendingFeature("当前没有可打开的批次。");
      return;
    }
    this.activeBatchName = batch.name;
    if (this.isOpeningDingtalk) return;
    this.isOpeningDingtalk = true;
    try {
      const result = await this.call("overseas_costing.api.batch.get_dingtalk_order_link", {
        batch_name: batch.name,
      });
      const order = result.dingtalk_order || {};
      if (!order.can_open || !order.open_url) {
        this.showPendingFeature("当前批次还没有关联钉钉审批链接，请先从国际物流单或采购支出单补来源信息。");
        return;
      }

      if (order.open_mode === "desktop_protocol") {
        window.location.href = order.open_url;
        frappe.show_alert({ message: "正在唤起钉钉客户端", indicator: "blue" });
        return;
      }

      const opened = window.open(order.open_url, "_blank", "noopener,noreferrer");
      if (!opened) {
        frappe.msgprint({
          title: "钉钉订单",
          message: `浏览器拦截了新窗口，请点击链接打开：<br><a href="${this.escape(order.open_url)}" target="_blank" rel="noopener noreferrer">${this.escape(order.open_url)}</a>`,
          indicator: "orange",
        });
      }
    } catch (error) {
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
    this.renderAuditList();
    this.updateSearchResult();
    this.updateRecalculateAction();
  }

  renderBatchList() {
    this.renderTable();
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
    this.$root.find("[data-area='table-title']").text("报关/来源单层级列表");
    this.$root.find("[data-area='table-count']").text(`${this.visibleBatches.length} 个报关/来源单块`);
    this.updateHierarchySummary();

    if (!this.visibleBatches.length) {
      this.$root.find("[data-area='table']").html(`<div class="ocw-muted ocw-table-empty">暂无匹配的报关/来源单块</div>`);
      return;
    }

    const rows = this.visibleBatches.map((batch) => this.renderBatchRows(batch)).join("");
    this.$root.find("[data-area='table']").html(`
      <table class="ocw-hierarchy-table">
        <colgroup>
          <col class="ocw-col-toggle" />
          <col class="ocw-col-customs" />
          <col class="ocw-col-waybill" />
          <col class="ocw-col-count" />
          <col class="ocw-col-money" />
          <col class="ocw-col-money-wide" />
          <col class="ocw-col-money" />
          <col class="ocw-col-value" />
          <col class="ocw-col-action" />
        </colgroup>
        <thead>
          <tr>
            <th></th>
            <th>报关/来源单号</th>
            <th>运单/物流单号</th>
            <th>SKU数</th>
            <th>中国杂费 RMB</th>
            <th>折合 MXN</th>
            <th>中国海运 USD</th>
            <th>采购货值</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    `);
    this.renderDiffPanel();
    this.updateRecalculateAction();
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
    const totalGoodsValue = hasLoadedItems ? this.sumBatchNumber(batch.name, "goods_value") : batch.total_goods_value;
    const statusInfo = this.batchStatusInfo(batch.status);
    const importedClass = this.lastImportedBatchNames.has(batch.name) ? "imported" : "";
    this.activeBatchName = this.activeBatchName || batch.name;
    return `
      <tr class="ocw-parent-row ${isExpanded ? "expanded" : ""} ${importedClass}">
        <td>
          <button class="ocw-tree-toggle" data-action="toggle-batch" data-batch-name="${this.escape(batch.name)}" aria-expanded="${isExpanded ? "true" : "false"}">
            ${isExpanded ? "-" : "+"}
          </button>
        </td>
        <td>
          <strong>${this.renderParentValue(customsNo, "customs_no")}</strong>
          <small>${this.escape(sourceRange)}</small>
          <span class="ocw-status ${this.escape(this.statusClass(batch.status))}">${this.escape(statusInfo.label)}</span>
        </td>
        <td>
          <strong>${this.renderParentValue(waybillNo, "waybill_no")}</strong>
          <small>${this.escape(this.transportLabel(batch.transport_mode || firstItem.transport_mode))}</small>
        </td>
        <td class="ocw-num-cell">${this.escape(String(itemCount))}</td>
        <td class="ocw-money-cell">${this.escape(this.formatValue(this.firstBatchValue(batch.name, "china_misc_rmb")))}</td>
        <td class="ocw-money-cell">${this.escape(this.formatValue(this.firstBatchValue(batch.name, "china_misc_mxn")))}</td>
        <td class="ocw-money-cell">${this.escape(this.formatValue(this.firstBatchValue(batch.name, "china_ocean_usd")))}</td>
        <td class="ocw-money-cell">${this.escape(this.formatValue(totalGoodsValue))}</td>
        <td class="ocw-row-actions">
          <div class="ocw-row-action-group">
            <button class="ocw-outline-btn ocw-mini-btn" data-action="open-dingtalk" data-batch-name="${this.escape(batch.name)}">审批单</button>
            <button class="ocw-outline-btn ocw-mini-btn" data-action="refresh-batch" data-batch-name="${this.escape(batch.name)}">刷新数据</button>
            <button class="ocw-danger-btn ocw-mini-btn" data-action="delete-batch" data-batch-name="${this.escape(batch.name)}">删除</button>
          </div>
        </td>
      </tr>
    `;
  }

  renderChildRow(batch) {
    const items = this.batchItems[batch.name] || [];
    return `
      <tr class="ocw-child-row">
        <td colspan="9">
          <div class="ocw-child-table-shell">
            <div class="ocw-child-table-toolbar">
              <span>SKU 成本分摊明细 / 物料详情 · ${items.length} 行</span>
              <button class="ocw-outline-btn ocw-mini-btn" data-action="add-material" data-batch-name="${this.escape(batch.name)}">+ 添加新物料</button>
            </div>
            ${this.renderChildTable(batch)}
          </div>
        </td>
      </tr>
    `;
  }

  sourceLabel(batch, firstItem = {}) {
    const explicit = firstItem.source_range || firstItem.source_sheet || batch.source_range || batch.source_sheet;
    if (this.hasText(explicit)) return explicit;
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
          <th class="${sticky} ${this.escape(this.columnAlignClass(column))}" title="${this.escape(column.excel_col + " " + column.label)}">
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
            return `
              <td
                class="${sticky} ${this.escape(this.columnAlignClass(column))} ${editable ? "ocw-editable-cell" : "ocw-readonly-cell"}"
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
      <table class="ocw-child-sku-table">
        <colgroup>${colgroup}<col class="ocw-col-row-action" /></colgroup>
        <thead><tr>${head}<th class="ocw-row-action-head">操作</th></tr></thead>
        <tbody>${body}</tbody>
      </table>
    `;
  }

  renderHeaderCell(column) {
    const parts = this.splitHeaderLabel(column.label);
    const secondary = parts.secondary ? `<span class="ocw-sku-header-secondary">${this.escape(parts.secondary)}</span>` : "";
    return `
      <div class="ocw-sku-header-cell">
        <span class="ocw-sku-header-code">${this.escape(column.excel_col)}</span>
        <span class="ocw-sku-header-primary">${this.escape(parts.primary)}</span>
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
    if (this.visibleBatches.length) {
      $result.removeClass("empty").addClass("active").text(`筛出 ${this.visibleBatches.length} 个报关/运单块 · 共 ${this.countVisibleItems()} 行 SKU（已自动展开）`);
    } else {
      $result.removeClass("active").addClass("empty").text("未找到匹配的报关/运单块");
    }
  }

  updateRecalculateAction() {
    if (!this.$root) return;
    const batch = this.getVisibleActiveBatch();
    const $button = this.$root.find("[data-action='recalculate']");
    if (!$button.length) return;

    $button.removeClass("needs-recalculate is-calculated").attr("title", "");
    if (!batch) {
      $button.text("重新试算").prop("disabled", true).attr("title", "暂无可试算批次");
      return;
    }

    const statusInfo = this.batchStatusInfo(batch.status);
    $button.prop("disabled", false);
    if (statusInfo.needsRecalculate) {
      $button.addClass("needs-recalculate").text("待重算 · 重新试算").attr("title", statusInfo.suggestion);
      return;
    }

    if (String(batch.status || "").toLowerCase().includes("calculated")) {
      $button.addClass("is-calculated").text("重新试算").attr("title", "当前批次已试算，可按需重新计算");
      return;
    }

    $button.text("重新试算").attr("title", "对当前批次重新计算分摊和综合成本");
  }

  updateHierarchySummary() {
    const batchCount = this.visibleBatches.length;
    const label = this.hasActiveFilters()
      ? `筛出 ${batchCount} 个报关/运单块 · 点击 + 展开 SKU 明细`
      : `${batchCount} 个报关/运单块 · 点击 + 展开 SKU 明细`;
    this.$root.find("[data-area='hierarchy-summary']").text(label);
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
    const html = this.auditEvents.map((event) => this.renderAuditEvent(event)).join("");
    this.$root.find("[data-area='audit-list']").html(html);
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
    return `
      <li class="ocw-audit-change-row">
        <span class="ocw-audit-time">${this.escape(event.time)}</span>
        ${actor}
        <div class="ocw-audit-change">
          <strong>${this.escape(title)}</strong>
          <div class="ocw-audit-values">
            <em class="ocw-audit-old">${this.escape(this.formatAuditValue(change.oldValue))}</em>
            <i>→</i>
            <em class="ocw-audit-new">${this.escape(this.formatAuditValue(change.newValue))}</em>
          </div>
        </div>
      </li>
    `;
  }

  renderDiffPanel() {
    const batch = this.getVisibleActiveBatch();
    if (!batch) {
      this.$root.find("[data-area='diff-panel']").html(`
        <div class="ocw-diff-table">
          <div class="ocw-diff-head"><span>检查项</span><span>当前状态</span><span>处理建议</span></div>
          <div><span>当前批次</span><b class="ocw-check-warn">未选择</b><strong>先导入或查询一条批次</strong></div>
        </div>
      `);
      return;
    }

    const items = this.batchItems[batch.name] || [];
    const rows = this.buildDataCheckRows(batch, items);
    this.$root.find("[data-area='diff-panel']").html(`
      <div class="ocw-diff-table">
        <div class="ocw-diff-head"><span>检查项</span><span>当前状态</span><span>处理建议</span></div>
        ${rows
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

  buildDataCheckRows(batch, items) {
    const customsNo = batch.customs_no || this.firstLoadedValue(items, "customs_no");
    const waybillNo = batch.waybill_no || this.firstLoadedValue(items, "waybill_no");
    const sourceNo = batch.batch_no || this.firstLoadedValue(items, "source_doc_no");
    const itemCount = items.length || Number(batch.item_count || 0);
    const goodsValue = items.length ? this.sumRowsNumber(items, "goods_value") : Number(batch.total_goods_value || 0);
    const grossWeight = items.length ? this.sumRowsNumber(items, "gross_weight_kg") : Number(batch.total_gross_weight_kg || 0);
    const freightAlloc = items.length ? this.sumRowsNumber(items, "freight_alloc_rmb") : 0;
    const totalCost = items.length
      ? this.sumRowsNumber(items, "total_cost_rmb")
      : Number(batch.actual_total_cost_rmb || batch.estimated_total_cost_rmb || 0);
    const manualCount = items.filter((row) => Number(row.manual_override_flag || 0) === 1).length;
    const batchStatus = this.batchStatusInfo(batch.status);

    const baseMissing = [];
    if (!customsNo) baseMissing.push("报关单号");
    if (!waybillNo) baseMissing.push("运单号");
    const hasSourceOnly = !customsNo && !waybillNo && this.hasText(sourceNo);

    const missingCode = this.countRows(items, (row) => !this.hasText(row.material_code));
    const missingName = this.countRows(items, (row) => !this.hasText(row.product_name));
    const badQuantity = this.countRows(items, (row) => !this.isPositive(row.quantity));
    const badPrice = this.countRows(items, (row) => !this.isPositive(row.unit_price));
    const badGoods = this.countRows(items, (row) => !this.isPositive(row.goods_value));
    const badWeight = this.countRows(items, (row) => !this.isPositive(row.gross_weight_kg));
    const badUnitCost = this.countRows(items, (row) => !this.isPositive(row.total_unit_rmb));
    const needsRecalculate = batchStatus.needsRecalculate || badUnitCost > 0;

    return [
      {
        label: "核算状态",
        status: batchStatus.label,
        statusClass: batchStatus.statusClass,
        suggestion: batchStatus.suggestion,
      },
      {
        label: "批次基础字段",
        status: hasSourceOnly ? "待关联" : baseMissing.length ? "待补" : "完整",
        statusClass: baseMissing.length ? "ocw-check-warn" : "ocw-check-ok",
        suggestion: hasSourceOnly
          ? `${sourceNo} 已作为来源单号，后续补报关/运单或物流单号`
          : baseMissing.length
          ? `缺少${baseMissing.join("、")}`
          : `${customsNo || "--"} / ${waybillNo || "--"}`,
      },
      {
        label: "物料主数据",
        status: missingCode || missingName ? "待补" : `${itemCount} 行`,
        statusClass: missingCode || missingName ? "ocw-check-warn" : "ocw-check-ok",
        suggestion:
          missingCode || missingName
            ? `物料编码缺 ${missingCode} 行，物料名称缺 ${missingName} 行`
            : "物料编码和名称已具备",
      },
      {
        label: "采购货值",
        status: badQuantity || badPrice || badGoods ? "需核对" : this.formatNumber(goodsValue),
        statusClass: badQuantity || badPrice || badGoods ? "ocw-check-warn" : "ocw-check-ok",
        suggestion:
          badQuantity || badPrice || badGoods
            ? `数量异常 ${badQuantity} 行，单价异常 ${badPrice} 行，货值异常 ${badGoods} 行`
            : "可用于按货值分摊",
      },
      {
        label: "重量分摊基础",
        status: badWeight ? "需补重量" : `${this.formatNumber(grossWeight)} KG`,
        statusClass: badWeight ? "ocw-check-warn" : "ocw-check-ok",
        suggestion: badWeight ? `毛重缺失或为 0：${badWeight} 行` : "可用于国际运费按重量分摊",
      },
      {
        label: "试算结果",
        status: needsRecalculate ? "待重算" : this.formatNumber(totalCost),
        statusClass: needsRecalculate ? "ocw-check-warn" : "ocw-check-ok",
        suggestion: batchStatus.needsRecalculate
          ? "明细已修改，请点击重新试算后再复核成本"
          : badUnitCost
          ? `综合单价缺失或为 0：${badUnitCost} 行，点击重新试算`
          : `已生成综合成本，国际运费分摊 ${this.formatNumber(freightAlloc)} RMB`,
      },
      {
        label: "修改留痕",
        status: manualCount ? `${manualCount} 行` : "暂无",
        statusClass: manualCount ? "ocw-check-info" : "ocw-check-ok",
        suggestion: manualCount ? "手工修改已写入修改记录" : "双击修改后会进入修改记录",
      },
    ];
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
    if (this.expandedBatchNames.has(batchName)) {
      this.expandedBatchNames.delete(batchName);
    } else {
      const batch = this.findBatch(batchName);
      await this.loadBatchItems(batchName, batch ? batch.current_version : null);
      this.expandedBatchNames.add(batchName);
    }
    this.renderTable();
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

  openAddMaterialDialog(batchName) {
    const batch = this.findBatch(batchName);
    if (!batch) return;
    this.activeBatchName = batch.name;
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
            dialog.hide();
            await this.createMaterial(batch, itemPayload);
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
    } catch (error) {
      this.showError(error);
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

  startCellEdit($cell, event = null) {
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

    $cell.removeData("cancelled saving");
    $cell.data("original-html", $cell.html());
    $cell.addClass("is-editing");

    if (options) {
      const optionHtml = options
        .map((option) => `<option value="${this.escape(option)}" ${String(option) === oldValue ? "selected" : ""}>${this.escape(this.transportLabel(option))}</option>`)
        .join("");
      $cell.html(`<select class="ocw-cell-editor ocw-cell-select" aria-label="${this.escape(label)}">${optionHtml}</select>`);
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
    const newValue = this.normalizeEditorValue($editor.val());
    const fieldname = $cell.attr("data-fieldname");
    const fieldLabel = $cell.attr("data-field-label") || fieldname;
    const batchName = $cell.attr("data-batch-name");
    const itemName = $cell.attr("data-item-name");
    const versionName = $cell.attr("data-version-name") || null;
    const isSpecialOverride = $cell.attr("data-special-override") === "1";
    const itemLabel = this.getLocalItemLabel(batchName, itemName);

    if (newValue === oldValue) {
      this.cancelCellEdit($cell);
      return;
    }

    const confirmed = await this.requestEditConfirm(fieldLabel, newValue);
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
    const itemFilters = ["material_code", "product_name", "import_name", "hs_code", "category"];
    return this.batches.filter((batch) => {
      if (customs && !this.lower(batch.customs_no).includes(customs)) return false;
      if (waybill && !this.lower(batch.waybill_no).includes(waybill)) return false;
      const items = this.batchItems[batch.name] || [];
      return itemFilters.every((fieldname) => {
        const needle = this.lower(this.filters[fieldname]);
        if (!needle) return true;
        return items.some((item) => this.lower(item[fieldname]).includes(needle));
      });
    });
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

  versionLabel(version) {
    if (!version) return "";
    const type = version.version_type || "";
    if (type === "ESTIMATED") return "暂估版";
    if (type === "ACTUAL") return "实际版";
    if (type === "Estimated") return "暂估版";
    if (type === "Actual") return "实际版";
    return version.version_code || type || "";
  }

  transportLabel(value) {
    if (!value) return "未指定";
    const labels = {
      SEA: "海运",
      AIR: "空运",
      EXPRESS: "快递",
    };
    const key = String(value).trim().toUpperCase();
    return labels[key] || String(value);
  }

  batchStatusInfo(status) {
    const value = String(status || "").trim();
    const normalized = value.toLowerCase();
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
        suggestion: "可继续核对费用池和分摊结果",
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
