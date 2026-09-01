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

