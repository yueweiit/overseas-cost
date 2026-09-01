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
