
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

