/* LOQ CARE — سلوكيات الواجهة المشتركة (الدفعة 2)
   1) فلاتر الأعمدة للجداول (شبيهة بـ Excel، أكثر من فلتر فنفس الوقت)
   2) نافذة تأكيد موحدة للإجراءات الحساسة (data-confirm)
   3) نافذة إرسال إشعار للطبيب (data-notify-url)
   4) تتبع تغييرات تعيين الفريق (حفظ / غير محفوظ)
   5) نموذج إضافة عضو الفريق: إظهار الحقول حسب النوع
*/
(function () {
    'use strict';

    function norm(s) { return (s || '').toString().toLowerCase().replace(/\s+/g, ' ').trim(); }
    function store(key, val) { try { sessionStorage.setItem(key, JSON.stringify(val)); } catch (e) { /* غير متاح */ } }
    function load(key) { try { return JSON.parse(sessionStorage.getItem(key) || 'null'); } catch (e) { return null; } }
    function el(tag, cls, text) {
        var n = document.createElement(tag);
        if (cls) n.className = cls;
        if (text) n.textContent = text;
        return n;
    }

    /* =====================================================
       1) فلاتر الأعمدة
       الجدول:  <table data-filterable data-filter-key="admin-cases">
       العمود:  <th data-filter="text|select|date">
       الخلية:  data-value="..." (اختياري) يعوض النص الظاهر فالفلترة
       ===================================================== */
    function cellValue(td) {
        if (!td) return '';
        return td.hasAttribute('data-value') ? td.getAttribute('data-value') : td.textContent;
    }

    function initTable(table) {
        if (table.__cfInit) return;
        table.__cfInit = true;
        var heads = Array.prototype.slice.call(table.querySelectorAll('thead th'));
        var rows = Array.prototype.slice.call(table.querySelectorAll('tbody tr'));
        if (!rows.length) return;

        var cols = [];
        heads.forEach(function (th, i) {
            var type = th.getAttribute('data-filter');
            if (type) cols.push({ index: i, type: type, label: th.textContent.trim() });
        });
        if (!cols.length) return;

        var wrapper = table.closest('.data-table-wrapper') || table;
        var storeKey = 'cf:' + location.pathname + ':' + (table.getAttribute('data-filter-key') || 'table');
        var saved = load(storeKey) || {};
        var inputs = {};

        var panel = el('div', 'col-filters');
        var toggle = el('button', 'cf-toggle');
        toggle.type = 'button';
        toggle.setAttribute('aria-expanded', 'false');
        var toggleText = el('span', null, 'تصفية حسب الأعمدة');
        var badge = el('span', 'cf-badge');
        badge.hidden = true;
        toggle.appendChild(toggleText);
        toggle.appendChild(badge);
        var body = el('div', 'cf-body');
        var grid = el('div', 'cf-grid');

        function field(label, control) {
            var wrap = el('label', 'cf-field');
            wrap.appendChild(el('span', null, label));
            wrap.appendChild(control);
            grid.appendChild(wrap);
        }
        function textInput(placeholder) {
            var i = el('input'); i.type = 'search'; i.placeholder = placeholder || ''; i.autocomplete = 'off';
            return i;
        }

        // بحث عام فكل الأعمدة
        var globalInput = textInput('ابحث في كل الأعمدة…');
        globalInput.value = saved.global || '';
        field('بحث عام', globalInput);

        cols.forEach(function (c) {
            var k = 'c' + c.index;
            if (c.type === 'select') {
                var sel = el('select');
                var all = el('option', null, 'الكل'); all.value = '';
                sel.appendChild(all);
                var seen = {};
                rows.forEach(function (tr) {
                    var v = cellValue(tr.children[c.index]).trim();
                    if (v && !seen[v]) seen[v] = true;
                });
                Object.keys(seen).sort(function (a, b) { return a.localeCompare(b, 'ar'); }).forEach(function (v) {
                    var o = el('option', null, v); o.value = v; sel.appendChild(o);
                });
                sel.value = saved[k] || '';
                inputs[k] = sel;
                field(c.label, sel);
            } else if (c.type === 'date') {
                var from = el('input'); from.type = 'date'; from.value = saved[k + 'f'] || '';
                var to = el('input'); to.type = 'date'; to.value = saved[k + 't'] || '';
                inputs[k + 'f'] = from; inputs[k + 't'] = to;
                var pair = el('div', 'cf-date-pair');
                var f1 = el('label'); f1.appendChild(el('small', null, 'من')); f1.appendChild(from);
                var f2 = el('label'); f2.appendChild(el('small', null, 'إلى')); f2.appendChild(to);
                pair.appendChild(f1); pair.appendChild(f2);
                var wrap = el('div', 'cf-field');
                wrap.appendChild(el('span', null, c.label));
                wrap.appendChild(pair);
                grid.appendChild(wrap);
            } else {
                var ti = textInput('بحث…');
                ti.value = saved[k] || '';
                inputs[k] = ti;
                field(c.label, ti);
            }
        });

        var actions = el('div', 'cf-actions');
        var result = el('span', 'cf-result muted');
        result.setAttribute('aria-live', 'polite');
        var clear = el('button', 'btn-small cf-clear', 'مسح الفلاتر');
        clear.type = 'button';
        actions.appendChild(result);
        actions.appendChild(clear);
        body.appendChild(grid);
        body.appendChild(actions);
        panel.appendChild(toggle);
        panel.appendChild(body);
        wrapper.parentNode.insertBefore(panel, wrapper);

        var empty = el('p', 'muted cf-empty', 'لا توجد نتائج مطابقة للفلاتر الحالية.');
        empty.hidden = true;
        wrapper.parentNode.insertBefore(empty, wrapper.nextSibling);

        function setOpen(open) {
            body.hidden = !open;
            toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
        }
        toggle.addEventListener('click', function () { setOpen(body.hidden); });

        function apply() {
            var g = norm(globalInput.value);
            var state = { global: globalInput.value };
            var active = g ? 1 : 0;
            var f = {};
            cols.forEach(function (c) {
                var k = 'c' + c.index;
                if (c.type === 'date') {
                    f[k] = { from: inputs[k + 'f'].value, to: inputs[k + 't'].value };
                    state[k + 'f'] = f[k].from; state[k + 't'] = f[k].to;
                    if (f[k].from) active++;
                    if (f[k].to) active++;
                } else {
                    f[k] = norm(inputs[k].value);
                    state[k] = inputs[k].value;
                    if (f[k]) active++;
                }
            });

            var shown = 0;
            rows.forEach(function (tr) {
                var ok = true;
                if (g && norm(tr.textContent).indexOf(g) === -1) ok = false;
                for (var i = 0; ok && i < cols.length; i++) {
                    var c = cols[i], k = 'c' + c.index, v = cellValue(tr.children[c.index]);
                    if (c.type === 'select') {
                        if (f[k] && norm(v) !== f[k]) ok = false;
                    } else if (c.type === 'date') {
                        var d = v.trim().slice(0, 10);
                        if (f[k].from && (!d || d < f[k].from)) ok = false;
                        if (f[k].to && (!d || d > f[k].to)) ok = false;
                    } else if (f[k] && norm(v).indexOf(f[k]) === -1) {
                        ok = false;
                    }
                }
                tr.classList.toggle('cf-hide', !ok);
                if (ok) shown++;
            });

            empty.hidden = shown > 0;
            wrapper.hidden = shown === 0;
            result.textContent = 'عرض ' + shown + ' من ' + rows.length;
            badge.hidden = active === 0;
            badge.textContent = active;
            clear.disabled = active === 0;
            store(storeKey, state);
        }

        Object.keys(inputs).forEach(function (k) {
            inputs[k].addEventListener('input', apply);
            inputs[k].addEventListener('change', apply);
        });
        globalInput.addEventListener('input', apply);
        clear.addEventListener('click', function () {
            globalInput.value = '';
            Object.keys(inputs).forEach(function (k) { inputs[k].value = ''; });
            apply();
        });

        apply();
        // مفتوح على الشاشات الكبيرة، ومطوي على الجوال (إلا كانت فلاتر مفعلة)
        var hasActive = !badge.hidden;
        setOpen(hasActive || !window.matchMedia('(max-width: 640px)').matches);
    }

    function initFilters() { document.querySelectorAll('table[data-filterable]').forEach(initTable); }
    initFilters();

    /* =====================================================
       2) نافذة التأكيد: <form data-confirm="..." [data-confirm-ok="حذف"] [data-confirm-danger]>
       ===================================================== */
    function submitForm(form) {
        if (typeof form.requestSubmit === 'function') { form.requestSubmit(); } else { form.submit(); }
    }

    var canDialog = typeof document.createElement('dialog').showModal === 'function';

    function closeDialog(dlg) {
        if (typeof dlg.close === 'function') { dlg.close(); }
        dlg.remove();
    }

    function openDialog(build) {
        var dlg = document.createElement('dialog');
        dlg.className = 'app-dialog';
        // الأزرار كتستعمل dlg.dismiss() بدل dlg.close() مباشرة (تتعامل مع المتصفحات القديمة)
        dlg.dismiss = function () { closeDialog(dlg); };
        build(dlg);
        document.body.appendChild(dlg);
        dlg.addEventListener('click', function (e) { if (e.target === dlg) closeDialog(dlg); });
        if (canDialog) { dlg.showModal(); } else { dlg.setAttribute('open', ''); }
        return dlg;
    }

    document.addEventListener('submit', function (e) {
        var form = e.target;
        var msg = form.getAttribute && form.getAttribute('data-confirm');
        if (!msg || form.__confirmed) return;
        e.preventDefault();
        var okLabel = form.getAttribute('data-confirm-ok') || 'تأكيد';
        var danger = form.hasAttribute('data-confirm-danger');
        if (!canDialog) {
            if (window.confirm(msg)) { form.__confirmed = true; submitForm(form); }
            return;
        }
        openDialog(function (dlg) {
            dlg.appendChild(el('h3', null, 'تأكيد الإجراء'));
            dlg.appendChild(el('p', null, msg));
            var row = el('div', 'dialog-actions');
            var cancel = el('button', 'btn-small', 'إلغاء'); cancel.type = 'button';
            var ok = el('button', 'btn-small ' + (danger ? 'btn-danger' : 'btn-primary'), okLabel); ok.type = 'button';
            cancel.addEventListener('click', function () { dlg.dismiss(); });
            ok.addEventListener('click', function () { form.__confirmed = true; dlg.dismiss(); submitForm(form); });
            row.appendChild(ok); row.appendChild(cancel);
            dlg.appendChild(row);
            cancel.focus();
        });
    }, true);

    /* =====================================================
       3) نافذة إرسال إشعار: أي عنصر فيه data-notify-url
       (data-notify-name, data-notify-prefill اختياريين)
       ===================================================== */
    document.addEventListener('click', function (e) {
        var btn = e.target.closest ? e.target.closest('[data-notify-url]') : null;
        if (!btn) return;
        e.preventDefault();
        var meta = document.querySelector('meta[name="csrf-token"]');
        var csrf = meta ? meta.getAttribute('content') : '';
        openDialog(function (dlg) {
            dlg.appendChild(el('h3', null, 'إرسال إشعار إلى ' + (btn.getAttribute('data-notify-name') || 'الطبيب')));
            var form = el('form');
            form.method = 'post';
            form.setAttribute('data-ajax', '');
            form.action = btn.getAttribute('data-notify-url');
            [['csrf_token', csrf], ['next', location.pathname + location.search]].forEach(function (p) {
                var h = el('input'); h.type = 'hidden'; h.name = p[0]; h.value = p[1]; form.appendChild(h);
            });
            var ta = el('textarea');
            ta.name = 'message'; ta.rows = 4; ta.required = true; ta.maxLength = 1000;
            ta.placeholder = 'اكتب نص الإشعار هنا…';
            ta.value = btn.getAttribute('data-notify-prefill') || '';
            form.appendChild(ta);
            var row = el('div', 'dialog-actions');
            var send = el('button', 'btn-small btn-primary', 'إرسال الإشعار'); send.type = 'submit';
            var cancel = el('button', 'btn-small', 'إلغاء'); cancel.type = 'button';
            cancel.addEventListener('click', function () { dlg.dismiss(); });
            form.addEventListener('submit', function () { send.disabled = true; send.textContent = 'جارٍ الإرسال…'; });
            row.appendChild(send); row.appendChild(cancel);
            form.appendChild(row);
            dlg.appendChild(form);
            ta.focus();
            ta.setSelectionRange(ta.value.length, ta.value.length);
        });
    });

    function initPageForms() {
    /* =====================================================
       4) تعيين الفريق: مؤشر "غير محفوظ" عند أي تغيير
       ===================================================== */
    var assignForm = document.getElementById('assign-form');
    if (assignForm) {
        var boxes = Array.prototype.slice.call(assignForm.querySelectorAll('input[type=checkbox]'));
        var initial = boxes.map(function (b) { return b.checked; });
        var note = document.getElementById('assign-unsaved');
        var submitBtn = assignForm.querySelector('button[type=submit]');
        var refresh = function () {
            var dirty = false;
            boxes.forEach(function (b, i) {
                var changed = b.checked !== initial[i];
                if (changed) dirty = true;
                var item = b.closest('.checkbox-item');
                if (item) item.classList.toggle('changed', changed);
            });
            if (note) note.hidden = !dirty;
            if (submitBtn) submitBtn.classList.toggle('is-dirty', dirty);
        };
        boxes.forEach(function (b) { b.addEventListener('change', refresh); });
        assignForm.addEventListener('submit', function () {
            if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = 'جارٍ الحفظ…'; }
        });
    }

    /* =====================================================
       5) نموذج عضو الفريق: الحقول حسب النوع (طبيب / أخصائي تغذية)
       ===================================================== */
    var typeForm = document.getElementById('member-form');
    if (typeForm) {
        var radios = Array.prototype.slice.call(typeForm.querySelectorAll('input[name=member_type]'));
        var rest = document.getElementById('member-fields');
        var blocks = Array.prototype.slice.call(typeForm.querySelectorAll('[data-for-type]'));
        var update = function () {
            var chosen = (radios.filter(function (r) { return r.checked; })[0] || {}).value || '';
            rest.hidden = !chosen;
            blocks.forEach(function (b) {
                var on = b.getAttribute('data-for-type') === chosen;
                b.hidden = !on;
                // الحقول المخفية كتتعطل: ما كتتبعتش وما كتمنعش الإرسال بـ required
                b.querySelectorAll('input, select, textarea').forEach(function (f) { f.disabled = !on; });
            });
            typeForm.querySelectorAll('select[data-other-toggle]').forEach(function (s) { toggleOther(s); });
        };
        var toggleOther = function (s) {
            var target = document.getElementById(s.getAttribute('data-other-toggle'));
            if (target) target.hidden = s.value !== 'أخرى';
        };
        typeForm.querySelectorAll('select[data-other-toggle]').forEach(function (s) {
            s.addEventListener('change', function () { toggleOther(s); });
        });
        radios.forEach(function (r) { r.addEventListener('change', update); });
        update();
    }
    }
    initPageForms();

    /* =====================================================
       6) تحديث جزئي بلا إعادة تحميل (#22)
       أي <form data-ajax> كيتبعت بـ fetch، وكنبدلو غير محتوى الصفحة (main) والعدادات،
       فالمستخدم كيبقى فنفس موضع التمرير ونفس الفلاتر (محفوظة فـ sessionStorage).
       إلا فشل شي حاجة (شبكة، صفحة أخرى...) كنرجعو للإرسال العادي.
       ===================================================== */
    function swapContent(doc) {
        var curMain = document.querySelector('main.container');
        var newMain = doc.querySelector('main.container');
        if (!curMain || !newMain) return false;
        var y = window.scrollY;
        curMain.innerHTML = newMain.innerHTML;
        var curNav = document.querySelector('#app-sidebar nav');
        var newNav = doc.querySelector('#app-sidebar nav');
        if (curNav && newNav) curNav.innerHTML = newNav.innerHTML;
        ['.mobile-header', '.top-header'].forEach(function (sel) {
            var c = document.querySelector(sel), n = doc.querySelector(sel);
            if (c && n) {
                var cb = c.querySelectorAll('.nav-badge, .mh-pending'), nb = n.querySelectorAll('.nav-badge, .mh-pending');
                if (cb.length === nb.length) { nb.forEach(function (x, i) { cb[i].outerHTML = x.outerHTML; }); }
            }
        });
        initFilters();
        initPageForms();
        document.dispatchEvent(new Event('loq:content'));
        window.scrollTo(0, y);
        return true;
    }

    var ajaxBusy = false, lastQueryDiffers = false;
    document.addEventListener('submit', function (e) {
        var form = e.target;
        if (e.defaultPrevented || !form.hasAttribute || !form.hasAttribute('data-ajax')) return;
        if (!window.fetch || !window.DOMParser || ajaxBusy) return;
        e.preventDefault();
        ajaxBusy = true;
        var data = new FormData(form);
        var submitter = e.submitter;
        if (submitter && submitter.name) data.append(submitter.name, submitter.value);
        var buttons = form.querySelectorAll('button[type=submit]');
        buttons.forEach(function (b) { b.disabled = true; });
        var dlg = form.closest && form.closest('dialog');

        fetch(form.action, { method: 'POST', body: data, credentials: 'same-origin', headers: { 'X-Requested-With': 'fetch' } })
            .then(function (res) {
                var finalUrl = new URL(res.url, location.href);
                lastQueryDiffers = finalUrl.search !== location.search;
                var ct = res.headers.get('content-type') || '';
                // صفحة أخرى (مثلاً redirect لصفحة تفاصيل) أو خطأ: ننتقل لها عادي
                if (!res.ok || ct.indexOf('text/html') === -1 || finalUrl.pathname !== location.pathname) {
                    location.href = res.ok ? finalUrl.href : location.href;
                    return null;
                }
                return res.text();
            })
            .then(function (html) {
                if (html === null || html === undefined) return;
                var doc = new DOMParser().parseFromString(html, 'text/html');
                doc.__needsRefetch = lastQueryDiffers;
                if (dlg && dlg.dismiss) dlg.dismiss();
                // الـ redirect كيضيع الـ query (مثلاً فلتر البحث): نعاودو نجيبو الصفحة الحالية بنفس الرابط
                // وكنحافظو على رسالة النجاح/الخطأ (flash) اللي جات فالجواب الأول
                if (doc.__needsRefetch) {
                    return fetch(location.href, { credentials: 'same-origin' }).then(function (r) { return r.text(); }).then(function (h2) {
                        var d2 = new DOMParser().parseFromString(h2, 'text/html');
                        var f1 = doc.querySelector('.flash-stack'), f2 = d2.querySelector('.flash-stack'), m2 = d2.querySelector('main.container');
                        if (f2) f2.remove();
                        if (f1 && m2) m2.insertBefore(f1.cloneNode(true), m2.firstChild);
                        if (!swapContent(d2)) location.reload();
                    });
                }
                if (!swapContent(doc)) location.reload();
            })
            .catch(function () {
                ajaxBusy = false;
                buttons.forEach(function (b) { b.disabled = false; });
                form.removeAttribute('data-ajax');
                submitForm(form);
            })
            .then(function () { ajaxBusy = false; });
    });
})();
