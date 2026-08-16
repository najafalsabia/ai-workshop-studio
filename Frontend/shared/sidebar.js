/* ─── Sidebar Component ─── 
   Auto-injected into every step page. Shows workshop database,
   Start Over, and Continue buttons. Features full workshops.db Integration. */

(function() {
  'use strict';

  // CSS for the sidebar
  const SIDEBAR_CSS = `
    #app-sidebar {
      position: fixed;
      top: 0;
      right: 0;
      width: 280px;
      height: 100vh;
      background: linear-gradient(180deg, #f0faf9 0%, #ffffff 100%);
      border-left: 1.5px solid var(--teal-soft, #b2dfdb);
      padding: 20px 14px;
      box-sizing: border-box;
      overflow-y: auto;
      z-index: 1100;
      display: flex;
      flex-direction: column;
      gap: 14px;
      font-family: 'Space Grotesk', 'Cairo', sans-serif;
      box-shadow: -2px 0 12px rgba(0,0,0,0.04);
      transition: transform 0.3s ease;
    }

    #app-sidebar .sidebar-header {
      display: flex;
      align-items: center;
      gap: 10px;
      padding-bottom: 10px;
      border-bottom: 1.5px solid var(--teal-soft, #b2dfdb);
    }

    #app-sidebar .sidebar-header h3 {
      margin: 0;
      font-size: 1.05rem;
      font-weight: 700;
      color: var(--teal-deep, #1a3c40);
    }

    #app-sidebar .sidebar-header .sidebar-icon {
      font-size: 1.3rem;
    }

    /* Tabs Layout */
    .sidebar-tabs {
      display: flex;
      background: #e8f5f3;
      border-radius: 8px;
      padding: 3px;
      gap: 4px;
    }

    .sidebar-tab-btn {
      flex: 1;
      padding: 8px 6px;
      font-size: 0.8rem;
      font-weight: 600;
      border: none;
      background: transparent;
      color: #555;
      border-radius: 6px;
      cursor: pointer;
      transition: all 0.2s;
      font-family: inherit;
    }

    .sidebar-tab-btn.active {
      background: var(--white, #fff);
      color: var(--teal-deep, #1a3c40);
      box-shadow: 0 2px 6px rgba(0,0,0,0.05);
    }

    #app-sidebar .db-section {
      flex: 1;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }

    #app-sidebar .db-section h4 {
      margin: 0 0 4px;
      font-size: 0.85rem;
      font-weight: 600;
      color: var(--teal-deep, #1a3c40);
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }

    #app-sidebar .db-entries {
      display: flex;
      flex-direction: column;
      gap: 6px;
    }

    #app-sidebar .db-entry {
      background: var(--white, #fff);
      border: 1px solid var(--bg-ice, #e8f5f3);
      border-radius: 8px;
      padding: 8px 10px;
      font-size: 0.8rem;
      word-break: break-word;
    }

    #app-sidebar .db-entry .db-key {
      font-weight: 600;
      color: var(--teal-deep, #1a3c40);
      display: block;
      margin-bottom: 2px;
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.3px;
    }

    #app-sidebar .db-entry .db-val {
      color: #555;
      font-size: 0.8rem;
      max-height: 60px;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    #app-sidebar .db-entry.empty-state {
      color: #999;
      font-style: italic;
      text-align: center;
      border-style: dashed;
    }

    /* History database list */
    .history-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .history-card {
      background: var(--white, #fff);
      border: 1px solid #d8edea;
      border-radius: 8px;
      padding: 10px;
      font-size: 0.78rem;
      position: relative;
      transition: all 0.2s;
      display: flex;
      flex-direction: column;
      gap: 4px;
    }

    .history-card:hover {
      border-color: var(--teal-soft, #b2dfdb);
      box-shadow: 0 3px 8px rgba(0,0,0,0.03);
    }

    .history-card .h-title {
      font-weight: 700;
      color: var(--teal-deep, #1a3c40);
      font-size: 0.82rem;
    }

    .history-card .h-meta {
      color: #777;
      font-size: 0.72rem;
    }

    .history-card .h-actions {
      display: flex;
      gap: 6px;
      margin-top: 4px;
    }

    .history-card .btn-h-load {
      background: #e8f5f3;
      color: var(--teal-deep, #1a3c40);
      border: none;
      border-radius: 4px;
      padding: 4px 8px;
      font-weight: 600;
      cursor: pointer;
      font-size: 0.7rem;
      flex: 1;
      font-family: inherit;
    }

    .history-card .btn-h-load:hover {
      background: var(--teal-soft, #b2dfdb);
    }

    .history-card .btn-h-del {
      background: #fdf2f2;
      color: #e74c3c;
      border: none;
      border-radius: 4px;
      padding: 4px 6px;
      cursor: pointer;
      font-size: 0.7rem;
      font-family: inherit;
    }

    .history-card .btn-h-del:hover {
      background: #fde8e8;
    }

    #app-sidebar .sidebar-actions {
      display: flex;
      flex-direction: column;
      gap: 8px;
      padding-top: 12px;
      border-top: 1.5px solid var(--teal-soft, #b2dfdb);
    }

    #app-sidebar .sidebar-actions button {
      width: 100%;
      padding: 10px 14px;
      border: none;
      border-radius: 8px;
      font-weight: 600;
      font-size: 0.88rem;
      cursor: pointer;
      transition: all 0.2s ease;
      font-family: inherit;
    }

    #app-sidebar .btn-start-over {
      background: #e74c3c;
      color: #fff;
    }
    #app-sidebar .btn-start-over:hover {
      background: #c0392b;
    }

    #app-sidebar .btn-continue {
      background: var(--teal-deep, #1a3c40);
      color: #fff;
    }
    #app-sidebar .btn-continue:hover {
      opacity: 0.9;
    }

    /* Shift page content to the left when sidebar is active */
    body.has-sidebar .topbar,
    body.has-sidebar .step-progress,
    body.has-sidebar .page-main,
    body.has-sidebar footer {
      margin-right: 280px;
      margin-left: 0;
    }

    /* Sidebar toggle button (hamburger) positioned at the top right */
    #sidebar-toggle {
      position: fixed;
      top: 14px;
      right: 14px;
      z-index: 1200;
      background: var(--teal-deep, #1a3c40);
      color: #fff;
      border: none;
      border-radius: 8px;
      width: 36px;
      height: 36px;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      font-size: 1.2rem;
      box-shadow: 0 2px 8px rgba(0,0,0,0.15);
      transition: all 0.3s ease;
    }
    #sidebar-toggle:hover {
      opacity: 0.85;
    }

    body.has-sidebar #sidebar-toggle {
      right: 294px;
    }

    /* Push language toggle when sidebar is open */
    .lang-toggle {
      margin-right: 50px;
      transition: margin-right 0.3s ease;
    }
    body.has-sidebar .lang-toggle {
      margin-right: 340px;
    }

    body:not(.has-sidebar) #app-sidebar {
      transform: translateX(100%);
    }

    @media (max-width: 768px) {
      #app-sidebar { width: 250px; }
      body.has-sidebar .topbar,
      body.has-sidebar .step-progress,
      body.has-sidebar .page-main,
      body.has-sidebar footer {
        margin-right: 250px;
        margin-left: 0;
      }
      body.has-sidebar #sidebar-toggle { right: 264px; }
      body.has-sidebar .lang-toggle { margin-right: 310px; }
    }
  `;

  // Inject CSS
  const styleEl = document.createElement('style');
  styleEl.textContent = SIDEBAR_CSS;
  document.head.appendChild(styleEl);

  // Active Tab state: 'current' or 'history'
  let activeTab = 'current';

  // Workshop-relevant localStorage keys and their display labels
  const DB_KEYS = [
    { key: 'workshop_input', label: 'Workshop Input', labelAr: 'بيانات الورشة' },
    { key: 'chosen_title', label: 'Chosen Title', labelAr: 'العنوان المختار' },
    { key: 'plan_result', label: 'Workshop Plan', labelAr: 'خطة الورشة' },
    { key: 'content_result', label: 'Slide Content', labelAr: 'محتوى الشرائح' },
    { key: 'labs_result', label: 'Labs', labelAr: 'اللابات' },
    { key: 'quiz_result', label: 'Quiz', labelAr: 'الاختبار' },
    { key: 'quiz_approved', label: 'Quiz Approved', labelAr: 'الاختبار معتمد' }
  ];

  function getLastStep() {
    if (localStorage.getItem('quiz_approved')) return { page: 'step7.html', step: 6 };
    if (localStorage.getItem('quiz_result')) return { page: 'step6.html', step: 5 };
    if (localStorage.getItem('labs_result')) return { page: 'step6.html', step: 5 };
    if (localStorage.getItem('content_result')) return { page: 'step5.html', step: 4 };
    if (localStorage.getItem('plan_result')) return { page: 'step4.html', step: 3 };
    if (localStorage.getItem('chosen_title')) return { page: 'step3.html', step: 2 };
    if (localStorage.getItem('workshop_input')) return { page: 'step2.html', step: 1 };
    return null;
  }

  function truncate(str, max) {
    if (!str) return '';
    if (str.length <= max) return str;
    return str.substring(0, max) + '…';
  }

  function formatValue(key, raw) {
    try {
      const val = JSON.parse(raw);
      if (key === 'workshop_input') {
        return val.idea_input || val.idea_mode || '—';
      }
      if (key === 'chosen_title') {
        if (typeof val === 'object') return val.title_en || val.title_ar || JSON.stringify(val);
        return val;
      }
      if (key === 'plan_result') {
        const lo = val.learning_objectives;
        return lo ? (Array.isArray(lo) ? lo.length + ' objectives' : 'Has plan') : 'Has plan';
      }
      if (key === 'content_result') {
        const slides = val.slides || val.sections;
        return slides ? (Array.isArray(slides) ? slides.length + ' slides' : 'Has content') : 'Has content';
      }
      if (key === 'labs_result') {
        const labs = val.labs;
        return labs ? labs.length + ' labs' : 'Has labs';
      }
      if (key === 'quiz_result') {
        const q = val.quiz ? val.quiz : val;
        const qs = q.questions;
        return qs ? qs.length + ' questions' : 'Has quiz';
      }
      return truncate(JSON.stringify(val), 60);
    } catch {
      return truncate(raw, 60);
    }
  }

  function buildSidebar() {
    const isAr = document.documentElement.lang === 'ar';

    // Toggle button
    const toggleBtn = document.createElement('button');
    toggleBtn.id = 'sidebar-toggle';
    toggleBtn.innerHTML = '&#9776;';
    toggleBtn.title = isAr ? 'القائمة الجانبية' : 'Sidebar';
    toggleBtn.onclick = function() {
      document.body.classList.toggle('has-sidebar');
      localStorage.setItem('sidebar_open', document.body.classList.contains('has-sidebar') ? '1' : '0');
    };
    document.body.appendChild(toggleBtn);

    // Sidebar container
    const sidebar = document.createElement('aside');
    sidebar.id = 'app-sidebar';

    // Header & Tabs
    sidebar.innerHTML = `
      <div class="sidebar-header">
        <h3>${isAr ? 'قاعدة بيانات الورشة' : 'Workshop Database'}</h3>
      </div>
      <div class="sidebar-tabs">
        <button class="sidebar-tab-btn active" id="tab-btn-current" onclick="window.switchSidebarTab('current')">
          ${isAr ? 'الجلسة الحالية' : 'Current Session'}
        </button>
        <button class="sidebar-tab-btn" id="tab-btn-history" onclick="window.switchSidebarTab('history')">
          ${isAr ? 'سجل الورش' : 'History DB'}
        </button>
      </div>
      <div class="db-section" id="sidebar-db-entries"></div>
      <div class="sidebar-actions" id="sidebar-actions"></div>
    `;

    document.body.appendChild(sidebar);

    window.refreshSidebarData();

    // Restore sidebar state
    const sidebarOpen = localStorage.getItem('sidebar_open');
    if (sidebarOpen === '1') {
      document.body.classList.add('has-sidebar');
    }
  }

  window.switchSidebarTab = function(tabName) {
    activeTab = tabName;
    document.getElementById('tab-btn-current').classList.toggle('active', tabName === 'current');
    document.getElementById('tab-btn-history').classList.toggle('active', tabName === 'history');
    window.refreshSidebarData();
  };

  window.refreshSidebarData = async function() {
    const isAr = document.documentElement.lang === 'ar';
    const container = document.getElementById('sidebar-db-entries');
    const actionsContainer = document.getElementById('sidebar-actions');
    if (!container || !actionsContainer) return;

    if (activeTab === 'current') {
      // Build DB entries for the current session
      let hasAnyData = false;
      let entriesHTML = '';

      DB_KEYS.forEach(({ key, label, labelAr }) => {
        const raw = localStorage.getItem(key);
        if (raw) {
          hasAnyData = true;
          const displayVal = formatValue(key, raw);
          entriesHTML += `
            <div class="db-entry">
              <span class="db-key">${isAr ? labelAr : label}</span>
              <span class="db-val">${displayVal}</span>
            </div>
          `;
        }
      });

      if (!hasAnyData) {
        entriesHTML = `<div class="db-entry empty-state">${isAr ? 'لا توجد بيانات بعد' : 'No data yet'}</div>`;
      }

      container.innerHTML = `<h4>${isAr ? 'البيانات المحفوظة' : 'Stored Data'}</h4><div class="db-entries">${entriesHTML}</div>`;

      // Build actions
      const lastStep = getLastStep();
      let actionsHTML = '';

      if (lastStep) {
        const currentPage = window.location.pathname.split('/').pop();
        if (currentPage !== lastStep.page) {
          actionsHTML += `
            <button class="btn-continue" onclick="window.location.href='${lastStep.page}'">
              ${isAr ? 'متابعة الورشة' : 'Continue Workshop'}
            </button>
          `;
        }
      }

      actionsHTML += `
        <button class="btn-start-over" onclick="startOverWorkshop()">
          ${isAr ? 'بدء من الصفر' : 'Start Over'}
        </button>
      `;
      actionsContainer.innerHTML = actionsHTML;
    } else {
      // History Tab (from sqlite database via /api/workshops)
      container.innerHTML = `<h4>${isAr ? 'سجل الورش السابقة' : 'Past Workshops'}</h4><div class="loading-block" style="text-align:center; font-size:0.8rem; color:#777;">Loading history...</div>`;
      actionsContainer.innerHTML = '';

      try {
        const response = await fetch('/api/workshops');
        if (!response.ok) throw new Error('Failed to load history');
        const workshops = await response.json();

        if (!workshops || workshops.length === 0) {
          container.innerHTML = `<h4>${isAr ? 'سجل الورش السابقة' : 'Past Workshops'}</h4><div class="db-entry empty-state">${isAr ? 'لا توجد ورش محفوظة' : 'No past workshops found'}</div>`;
          return;
        }

        let historyHTML = '';
        workshops.forEach(w => {
          const dateStr = w.created_at ? new Date(w.created_at).toLocaleDateString(isAr ? 'ar-EG' : 'en-US', {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'}) : '—';
          historyHTML += `
            <div class="history-card" id="history-card-${w.id}">
              <div class="h-title">${w.title}</div>
              <div class="h-meta">${w.audience || '—'} | ${w.duration || '—'}</div>
              <div class="h-meta">${dateStr}</div>
              <div class="h-actions">
                <button class="btn-h-load" onclick="window.loadPastWorkshop(${w.id})">${isAr ? 'استرجاع' : 'Restore'}</button>
                <button class="btn-h-del" onclick="window.deletePastWorkshop(${w.id})">${isAr ? 'حذف' : 'Del'}</button>
              </div>
            </div>
          `;
        });

        container.innerHTML = `<h4>${isAr ? 'سجل الورش السابقة' : 'Past Workshops'}</h4><div class="history-list">${historyHTML}</div>`;
      } catch (err) {
        container.innerHTML = `<h4>${isAr ? 'سجل الورش السابقة' : 'Past Workshops'}</h4><div class="db-entry empty-state" style="color:#e74c3c;">${isAr ? 'فشل تحميل السجل' : 'Failed to load history'}</div>`;
      }
    }
  };

  window.loadPastWorkshop = async function(id) {
    const isAr = document.documentElement.lang === 'ar';
    const confirmed = confirm(
      isAr 
        ? 'هل ترغب في استرجاع هذه الورشة؟ سيؤدي ذلك لاستبدال الجلسة الحالية.'
        : 'Do you want to restore this workshop? This will overwrite the current session.'
    );
    if (!confirmed) return;

    try {
      const response = await fetch(`/api/workshops/${id}`);
      if (!response.ok) throw new Error('Failed to load workshop');
      const w = await response.json();

      // Clear current state first
      const lang = localStorage.getItem('lang');
      const sidebarOpen = localStorage.getItem('sidebar_open');
      localStorage.clear();
      if (lang) localStorage.setItem('lang', lang);
      if (sidebarOpen) localStorage.setItem('sidebar_open', sidebarOpen);

      // Restore all keys to localStorage
      if (w.title) {
        localStorage.setItem('chosen_title', JSON.stringify({title_en: w.title, title_ar: w.title}));
      }
      
      const inputVal = {
        idea_mode: w.plan ? 'have' : 'content',
        idea_input: w.title,
        field: '',
        audience: w.audience || '',
        age: w.age || '',
        duration: w.duration || '',
        goal: w.plan ? (w.plan.learning_objectives ? w.plan.learning_objectives.join(', ') : '') : '',
        notes: ''
      };
      localStorage.setItem('workshop_input', JSON.stringify(inputVal));

      if (w.plan) localStorage.setItem('plan_result', JSON.stringify(w.plan));
      if (w.content) localStorage.setItem('content_result', JSON.stringify(w.content));
      if (w.labs) localStorage.setItem('labs_result', JSON.stringify(w.labs));
      if (w.quiz) {
        localStorage.setItem('quiz_result', JSON.stringify(w.quiz));
        localStorage.setItem('quiz_approved', 'true');
      }

      alert(isAr ? 'تم استرجاع الورشة بنجاح!' : 'Workshop restored successfully!');
      
      // Redirect to export/download page directly
      window.location.href = 'step8.html';
    } catch (err) {
      console.error(err);
      alert(isAr ? 'عذراً، فشل استرجاع الورشة.' : 'Sorry, failed to restore workshop.');
    }
  };

  window.deletePastWorkshop = async function(id) {
    const isAr = document.documentElement.lang === 'ar';
    const confirmed = confirm(
      isAr 
        ? 'هل أنت متأكد من حذف هذه الورشة نهائياً من السجل؟' 
        : 'Are you sure you want to permanently delete this workshop from history?'
    );
    if (!confirmed) return;

    try {
      const response = await fetch(`/api/workshops/${id}`, { method: 'DELETE' });
      if (!response.ok) throw new Error('Delete failed');
      
      // Refresh database listing
      window.refreshSidebarData();
    } catch (err) {
      console.error(err);
      alert(isAr ? 'فشل الحذف.' : 'Failed to delete.');
    }
  };

  // Global function so the button onclick can reach it
  window.startOverWorkshop = function() {
    const isAr = document.documentElement.lang === 'ar';
    const confirmed = confirm(
      isAr
        ? 'هل أنت متأكد؟ سيتم حذف جميع بيانات الورشة الحالية والبدء من جديد.'
        : 'Are you sure? All current workshop data will be deleted and you will start fresh.'
    );
    if (!confirmed) return;

    // Clear all workshop keys but preserve lang and sidebar_open
    const lang = localStorage.getItem('lang');
    const sidebarOpen = localStorage.getItem('sidebar_open');
    localStorage.clear();
    if (lang) localStorage.setItem('lang', lang);
    if (sidebarOpen) localStorage.setItem('sidebar_open', sidebarOpen);

    window.location.href = 'step1.html';
  };

  // Build on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', buildSidebar);
  } else {
    buildSidebar();
  }
})();
