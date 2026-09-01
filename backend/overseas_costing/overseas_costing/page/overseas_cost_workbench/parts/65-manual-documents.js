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

