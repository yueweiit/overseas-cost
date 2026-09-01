
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
