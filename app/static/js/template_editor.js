// Template Editor — PDF.js region selection
const TemplateEditor = (() => {
    let pdfDoc = null;
    let currentPage = 1;
    let scale = 1.5;
    let regions = [];
    let isDrawing = false;
    let drawStart = null;
    let selectedRegionId = null;
    let templateId = null;

    const canvas = document.getElementById('pdf-canvas');
    const ctx = canvas.getContext('2d');
    const overlay = document.getElementById('region-overlay');
    const overlayCtx = overlay.getContext('2d');
    const regionList = document.getElementById('region-list');
    const regionForm = document.getElementById('region-form');
    const testResults = document.getElementById('test-results');

    // -------- PDF Loading --------
    async function init(tId) {
        templateId = tId;
        const sampleUrl = `/api/templates/${templateId}/sample`;
        const pdfjsLib = await import('/static/vendor/pdfjs/pdf.min.mjs');
        pdfjsLib.GlobalWorkerOptions.workerSrc = '/static/vendor/pdfjs/pdf.worker.min.mjs';
        try {
            pdfDoc = await pdfjsLib.getDocument(sampleUrl).promise;
            document.getElementById('page-count').textContent = pdfDoc.numPages;
            await renderPage(currentPage);
            await loadRegions();
        } catch (e) {
            console.error('Failed to load PDF:', e);
            document.getElementById('pdf-viewer').innerHTML = '<p class="error">Failed to load sample PDF. Upload a sample PDF first.</p>';
        }
    }

    async function renderPage(pageNum) {
        if (!pdfDoc) return;
        currentPage = pageNum;
        const page = await pdfDoc.getPage(pageNum);
        const viewport = page.getViewport({ scale });
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        overlay.width = viewport.width;
        overlay.height = viewport.height;
        await page.render({ canvasContext: ctx, viewport }).promise;
        drawAllRegions();
        document.getElementById('current-page').textContent = pageNum;
    }

    // -------- Coordinate conversion --------
    async function canvasToPdfPoint(canvasX, canvasY) {
        const page = await pdfDoc.getPage(currentPage);
        const viewport = page.getViewport({ scale });
        const [pdfX, pdfY] = viewport.convertToPdfPoint(canvasX, canvasY);
        return { x: Math.round(pdfX * 100) / 100, y: Math.round(pdfY * 100) / 100 };
    }

    async function pdfToCanvasPoint(pdfX, pdfY) {
        const page = await pdfDoc.getPage(currentPage);
        const viewport = page.getViewport({ scale });
        const [cx, cy] = viewport.convertToViewportPoint(pdfX, pdfY);
        return { x: cx, y: cy };
    }

    // -------- Drawing --------
    function getRoleColor(role) {
        const colors = { GROUP_BOUNDARY: '#e74c3c', PAGE_COUNTER: '#3498db', UNIQUE_ID: '#2ecc71', CUSTOM: '#f39c12' };
        return colors[role] || '#999';
    }

    async function drawAllRegions() {
        overlayCtx.clearRect(0, 0, overlay.width, overlay.height);
        for (const r of regions) {
            if (r.page !== currentPage) continue;
            const [p1, p2] = await Promise.all([
                pdfToCanvasPoint(r.x, r.y),
                pdfToCanvasPoint(r.x + r.width, r.y + r.height),
            ]);
            const x = p1.x, y = p1.y, w = p2.x - p1.x, h = p2.y - p1.y;
            const color = getRoleColor(r.role);
            overlayCtx.strokeStyle = color;
            overlayCtx.lineWidth = r.id === selectedRegionId ? 3 : 2;
            overlayCtx.strokeRect(x, y, w, h);
            overlayCtx.fillStyle = color;
            overlayCtx.font = '11px sans-serif';
            overlayCtx.fillText(r.name || r.role, x + 3, y - 4);
        }
    }

    // -------- Mouse handlers --------
    overlay.addEventListener('mousedown', async (e) => {
        const rect = overlay.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;

        // Check if clicking on a region (simple hit test)
        const hit = await hitTest(mx, my);
        if (hit) {
            if (selectedRegionId !== null && selectedRegionId !== hit.id) applyRegionForm();
            selectedRegionId = hit.id;
            selectRegionInList(hit.id);
            drawAllRegions();
            return;
        }

        isDrawing = true;
        drawStart = { x: mx, y: my };
        selectedRegionId = null;
        updateRegionForm(null);
        drawAllRegions();
    });

    overlay.addEventListener('mousemove', async (e) => {
        if (!isDrawing) return;
        const rect = overlay.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;
        drawAllRegions();
        overlayCtx.strokeStyle = '#fff';
        overlayCtx.lineWidth = 1;
        overlayCtx.setLineDash([4, 4]);
        overlayCtx.strokeRect(drawStart.x, drawStart.y, mx - drawStart.x, my - drawStart.y);
        overlayCtx.setLineDash([]);
    });

    overlay.addEventListener('mouseup', async (e) => {
        if (!isDrawing) return;
        isDrawing = false;
        const rect = overlay.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;
        const w = Math.abs(mx - drawStart.x);
        const h = Math.abs(my - drawStart.y);
        if (w < 5 || h < 5) return; // too small, ignore

        const p1 = await canvasToPdfPoint(Math.min(drawStart.x, mx), Math.min(drawStart.y, my));
        const p2 = await canvasToPdfPoint(Math.max(drawStart.x, mx), Math.max(drawStart.y, my));

        const region = {
            id: Date.now(),
            name: '',
            role: 'GROUP_BOUNDARY',
            page: currentPage,
            x: p1.x,
            y: p1.y,
            width: p2.x - p1.x,
            height: p2.y - p1.y,
            match_type: 'EXACT',
            match_pattern: '',
            priority: regions.length,
        };
        regions.push(region);
        selectedRegionId = region.id;
        renderRegionList();
        updateRegionForm(region);
        await drawAllRegions();
    });

    async function hitTest(mx, my) {
        for (let i = regions.length - 1; i >= 0; i--) {
            const r = regions[i];
            if (r.page !== currentPage) continue;
            const [p1, p2] = await Promise.all([
                pdfToCanvasPoint(r.x, r.y),
                pdfToCanvasPoint(r.x + r.width, r.y + r.height),
            ]);
            if (mx >= p1.x && mx <= p2.x && my >= p1.y && my <= p2.y) {
                return r;
            }
        }
        return null;
    }

    // -------- Region list --------
    function renderRegionList() {
        regionList.innerHTML = '';
        const pageRegions = regions.filter(r => r.page === currentPage);
        pageRegions.forEach(r => {
            const div = document.createElement('div');
            div.className = 'region-entry' + (r.id === selectedRegionId ? ' selected' : '');
            div.style.borderLeftColor = getRoleColor(r.role);
            div.innerHTML = `
                <span class="region-name">${r.name || r.role}</span>
                <span class="region-page">Page ${r.page}</span>
                <span class="region-coords">(${Math.round(r.x)}, ${Math.round(r.y)}) ${Math.round(r.width)}×${Math.round(r.height)}</span>
            `;
            div.onclick = () => { if (selectedRegionId !== null && selectedRegionId !== r.id) applyRegionForm(); selectedRegionId = r.id; selectRegionInList(r.id); updateRegionForm(r); drawAllRegions(); };
            regionList.appendChild(div);
        });
        if (pageRegions.length === 0) {
            regionList.innerHTML = '<p class="empty">No regions on this page. Click and drag on the PDF to create one.</p>';
        }
    }

    function selectRegionInList(id) {
        document.querySelectorAll('.region-entry').forEach(el => el.classList.remove('selected'));
        const idx = regions.findIndex(r => r.id === id);
        if (idx >= 0) {
            const entries = document.querySelectorAll('.region-entry');
            const pageRegions = regions.filter(r => r.page === currentPage);
            const pageIdx = pageRegions.findIndex(r => r.id === id);
            if (pageIdx >= 0 && entries[pageIdx]) entries[pageIdx].classList.add('selected');
        }
    }

    function updateRegionForm(r) {
        if (!r) {
            regionForm.style.display = 'none';
            return;
        }
        regionForm.style.display = 'block';
        document.getElementById('rf-name').value = r.name || '';
        document.getElementById('rf-role').value = r.role;
        document.getElementById('rf-page').value = r.page;
        document.getElementById('rf-x').value = Math.round(r.x * 100) / 100;
        document.getElementById('rf-y').value = Math.round(r.y * 100) / 100;
        document.getElementById('rf-w').value = Math.round(r.width * 100) / 100;
        document.getElementById('rf-h').value = Math.round(r.height * 100) / 100;
        document.getElementById('rf-match-type').value = r.match_type || 'EXACT';
        document.getElementById('rf-match-pattern').value = r.match_pattern || '';
        document.getElementById('rf-priority').value = r.priority || 0;
    }

    function applyRegionForm() {
        const idx = regions.findIndex(r => r.id === selectedRegionId);
        if (idx < 0) return;
        regions[idx].name = document.getElementById('rf-name').value;
        regions[idx].role = document.getElementById('rf-role').value;
        regions[idx].page = parseInt(document.getElementById('rf-page').value);
        regions[idx].x = parseFloat(document.getElementById('rf-x').value);
        regions[idx].y = parseFloat(document.getElementById('rf-y').value);
        regions[idx].width = parseFloat(document.getElementById('rf-w').value);
        regions[idx].height = parseFloat(document.getElementById('rf-h').value);
        regions[idx].match_type = document.getElementById('rf-match-type').value;
        regions[idx].match_pattern = document.getElementById('rf-match-pattern').value;
        regions[idx].priority = parseInt(document.getElementById('rf-priority').value);
        renderRegionList();
        drawAllRegions();
    }

    async function deleteSelectedRegion() {
        const idx = regions.findIndex(r => r.id === selectedRegionId);
        if (idx < 0) return;
        regions.splice(idx, 1);
        selectedRegionId = null;
        updateRegionForm(null);
        renderRegionList();
        await drawAllRegions();
    }

    // -------- API calls --------
    async function loadRegions() {
        try {
            const resp = await fetch(`/api/templates/${templateId}`);
            const tmpl = await resp.json();
            if (tmpl.regions) {
                regions = tmpl.regions.map(r => ({...r}));
            }
        } catch (e) { console.error('Failed to load template:', e); }
        renderRegionList();
        await drawAllRegions();
    }

    async function saveRegions() {
        if (selectedRegionId !== null) applyRegionForm();
        const payload = { regions: regions.map(r => ({
            name: r.name || r.role,
            role: r.role,
            page: r.page,
            x: r.x, y: r.y,
            width: r.width, height: r.height,
            match_type: r.match_type,
            match_pattern: r.match_pattern || null,
            priority: r.priority,
        }))};
        try {
            const resp = await fetch(`/api/templates/${templateId}/regions`, {
                method: 'PUT',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload),
            });
            if (resp.ok) {
                const saved = await resp.json();
                regions = saved;
                selectedRegionId = null;
                updateRegionForm(null);
                renderRegionList();
                await drawAllRegions();
                showToast('Regions saved');
            } else {
                showToast('Save failed: ' + resp.statusText, true);
            }
        } catch (e) { console.error('Save failed:', e); showToast('Save failed', true); }
    }

    async function testDetection() {
        if (regions.length === 0) { showToast('Add at least one region first', true); return; }
        await saveRegions(); // Save first, then test
        try {
            const resp = await fetch(`/api/templates/${templateId}/test-detect?debug=true`, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}' });
            const data = await resp.json();
            const docs = data.docs || data;
            let html = docs.length === 0
                ? '<p>No documents detected.</p>'
                : `<p><strong>Detected ${docs.length} document(s):</strong></p><ul>${docs.map(d =>
                    `<li>Doc ${d.index + 1}: ${d.sheet_count} sheet(s), pages ${d.start_page + 1}-${d.end_page + 1}, unique_id=${d.unique_id || 'none'}</li>`
                ).join('')}</ul>`;

            // Show per-page extraction debug if available
            if (data.debug) {
                html += '<details style="margin-top:1rem;"><summary><strong>Per-page extraction</strong> (click to expand)</summary>';
                html += `<p><small>Side-A pages: ${data.debug.side_a_pages.map(p => p + 1).join(', ')}</small></p>`;
                html += '<table style="font-size:0.85rem;width:100%;"><thead><tr><th>Page</th><th>Group Boundary</th><th>Page Counter</th><th>Unique ID</th></tr></thead><tbody>';
                for (const p of data.debug.pages) {
                    const gb = p.group_boundary ? Object.entries(p.group_boundary).map(([name, v]) => `<em>${name}:</em> raw="${v.raw}", matched="${v.matched ?? 'null'}"`).join('<br>') : '-';
                    const pc = p.page_counter ? Object.entries(p.page_counter).map(([name, v]) => `<em>${name}:</em> raw="${v.raw}", matched="${v.matched ?? 'null'}"`).join('<br>') : '-';
                    const uid = p.unique_id ? Object.entries(p.unique_id).map(([name, v]) => `<em>${name}:</em> raw="${v.raw}", matched="${v.matched ?? 'null'}"`).join('<br>') : '-';
                    html += `<tr><td>${p.page_label}</td><td>${gb}</td><td>${pc}</td><td>${uid}</td></tr>`;
                }
                html += '</tbody></table>';

                // Show full text sample from first few pages
                if (data.debug.full_text_sample) {
                    html += '<details style="margin-top:0.5rem;"><summary><strong>Full text on first 4 pages</strong> (click to expand)</summary>';
                    for (const ft of data.debug.full_text_sample) {
                        const escaped = ft.full_text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
                        html += `<p><strong>Page ${ft.page_label}</strong> (${ft.char_count} chars)</p>`;
                        html += `<pre style="font-size:0.75rem;background:#f8f8f8;padding:0.5rem;max-height:300px;overflow:auto;white-space:pre-wrap;">${escaped}</pre>`;
                    }
                    html += '</details>';
                }
                html += '</details>';
            }

            testResults.innerHTML = html;
            testResults.style.display = 'block';
        } catch (e) { console.error('Detection test failed:', e); showToast('Detection test failed', true); }
    }

    function showToast(msg, isError = false) {
        const toast = document.getElementById('toast');
        toast.textContent = msg;
        toast.className = 'toast' + (isError ? ' error' : '');
        toast.style.display = 'block';
        setTimeout(() => toast.style.display = 'none', 2000);
    }

    // -------- Live-apply form changes --------
    ['rf-name','rf-role','rf-page','rf-x','rf-y','rf-w','rf-h','rf-match-type','rf-match-pattern','rf-priority'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('change', () => applyRegionForm());
    });
    document.getElementById('rf-match-pattern')?.addEventListener('input', () => applyRegionForm());

    // -------- Public API --------
    return {
        init,
        renderPage,
        saveRegions,
        testDetection,
        deleteSelectedRegion,
        applyRegionForm,
        get currentPage() { return currentPage; },
        set currentPage(v) { currentPage = v; },
        get pdfDoc() { return pdfDoc; },
    };
})();

// Page init
document.addEventListener('DOMContentLoaded', () => {
    const templateId = document.getElementById('template-id')?.value;
    if (templateId) TemplateEditor.init(parseInt(templateId));

    document.getElementById('btn-prev-page')?.addEventListener('click', () => {
        if (TemplateEditor.currentPage > 1) TemplateEditor.renderPage(--TemplateEditor.currentPage);
    });
    document.getElementById('btn-next-page')?.addEventListener('click', () => {
        if (TemplateEditor.pdfDoc && TemplateEditor.currentPage < TemplateEditor.pdfDoc.numPages) TemplateEditor.renderPage(++TemplateEditor.currentPage);
    });
    document.getElementById('btn-save')?.addEventListener('click', () => TemplateEditor.saveRegions());
    document.getElementById('btn-test')?.addEventListener('click', () => TemplateEditor.testDetection());
    document.getElementById('btn-delete-region')?.addEventListener('click', () => TemplateEditor.deleteSelectedRegion());
    document.getElementById('btn-apply-form')?.addEventListener('click', () => TemplateEditor.applyRegionForm());
});
