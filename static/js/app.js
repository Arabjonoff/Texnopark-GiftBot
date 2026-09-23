/**
 * Telegram WebApp Integration & Main UI Controller
 *
 * Uchta bo'lim (pastki appbar orqali):
 *   1. spin    — baraban
 *   2. history — foydalanuvchining o'z yutuqlari va QR-kodlari
 *   3. winners — shu botda yutuq olganlarning umumiy ro'yxati
 *
 * Spin oqimi: /api/spin/ sovg'ani serverda aniqlaydi va darhol PENDING
 * yutuq sifatida saqlaydi -> g'alaba oynasi -> forma -> /api/claim-prize/.
 * Forma yuborilmasa, keyingi ochilishda o'sha sovg'a qayta taklif qilinadi.
 *
 * Yangi spin uchun shartlar (server ham tekshiradi): aksiya davom etayotgan
 * bo'lishi va foydalanuvchi majburiy kanallarga obuna bo'lgan bo'lishi kerak.
 */

document.addEventListener('DOMContentLoaded', () => {
  const tg = window.Telegram?.WebApp;
  const BG_COLOR = '#0b0f19';

  const tgAtLeast = (v) => !!(tg && tg.isVersionAtLeast && tg.isVersionAtLeast(v));

  if (tg) {
    tg.ready();
    tg.expand();
    // Telegram sarlavhasi va foni ilova rangiga mos bo'lsin
    if (tgAtLeast('6.1')) {
      try { tg.setHeaderColor(BG_COLOR); tg.setBackgroundColor(BG_COLOR); } catch (e) { /* eski klient */ }
    }
    if (tgAtLeast('7.10')) {
      try { tg.setBottomBarColor(BG_COLOR); } catch (e) { /* eski klient */ }
    }
    // Ro'yxatni pastga surganda ilova tasodifan yopilib qolmasin
    if (tgAtLeast('7.7')) {
      try { tg.disableVerticalSwipes(); } catch (e) { /* eski klient */ }
    }
  }

  const inTelegram = !!(tg && tg.initData && tg.initData.trim() !== '');
  const isLocalDev = ['localhost', '127.0.0.1'].includes(location.hostname);

  // Local dev'da server mock_ initData'ni qabul qiladi (DEBUG=True)
  const initDataRaw = inTelegram ? tg.initData : (isLocalDev ? 'mock_123456789_Oquvchi' : '');

  // ---------------------------------------------------------------- DOM

  const $ = (id) => document.getElementById(id);

  const spinBtn = $('spin-btn');
  const spinBtnText = $('spin-btn-text');
  const spinBtnIcon = $('spin-btn-icon');
  const soundToggleBtn = $('sound-toggle');
  const headerSubtitle = $('header-subtitle');
  const outsideTelegram = $('outside-telegram');
  const spinsCountBadge = $('spins-count-badge');

  const victoryModal = $('victory-modal');
  const victoryKicker = $('victory-kicker');
  const victoryPrizeBox = $('victory-prize-box');
  const victoryRarity = $('victory-rarity');
  const victoryPrizeEmoji = $('victory-prize-emoji');
  const victoryPrizeImg = $('victory-prize-img');
  const victoryPrizeTitle = $('victory-prize-title');
  const btnClaimVictory = $('btn-claim-victory');

  const leadModal = $('lead-modal');
  const leadForm = $('lead-form');
  const savedProfileBox = $('saved-profile');
  const savedName = $('saved-name');
  const savedPhone = $('saved-phone');
  const btnEditProfile = $('btn-edit-profile');
  const profileFields = $('profile-fields');
  const inputFirstName = $('input-first-name');
  const inputLastName = $('input-last-name');
  const inputPhone = $('input-phone');
  const phoneError = $('phone-error');
  const btnSubmitLead = $('btn-submit-lead');

  const campaignBanner = $('campaign-banner');
  const campaignMessage = $('campaign-message');
  const subscribeGate = $('subscribe-gate');
  const subscribeChannels = $('subscribe-channels');
  const dailyBonusCard = $('daily-bonus-card');
  const btnDailyBonus = $('btn-daily-bonus');

  const referralCard = $('referral-card');
  const referralTitle = $('referral-title');
  const referralHint = $('referral-hint');
  const friendSlots = $('friend-slots');
  const refLinkInput = $('ref-link-input');
  const btnCopyRef = $('btn-copy-ref');
  const btnShareTg = $('btn-share-tg');
  const invitedCountBadge = $('invited-count-badge');
  const pendingInvites = $('pending-invites');
  const pendingInvitesCount = $('pending-invites-count');

  const historyList = $('history-list');
  const historyEmpty = $('history-empty');
  const historyLoading = $('history-loading');
  const historyBadge = $('history-badge');

  const winnersList = $('winners-list');
  const winnersLoading = $('winners-loading');
  const winnersEmpty = $('winners-empty');
  const winnersError = $('winners-error');
  const winnersTotal = $('winners-total');
  const winnersTotalCount = $('winners-total-count');
  const btnLoadMoreWinners = $('btn-load-more-winners');
  const btnRetryWinners = $('btn-retry-winners');
  const winnersSubtitle = $('winners-subtitle');
  const boardWinners = $('board-winners');
  const boardReferrers = $('board-referrers');
  const referrersList = $('referrers-list');
  const referrersLoading = $('referrers-loading');
  const referrersEmpty = $('referrers-empty');

  const qrViewModal = $('qr-view-modal');
  const qrModalTitle = $('qr-modal-title');
  const qrModalQrcode = $('qr-modal-qrcode');
  const qrModalPromocode = $('qr-modal-promocode');
  const btnCloseQrModal = $('btn-close-qr-modal');
  const qrLocation = $('qr-location');
  const qrLocationAddress = $('qr-location-address');
  const btnOpenMap = $('btn-open-map');

  const rouletteEngine = new RouletteEngine('roulette-track', 'roulette-viewport');

  // ---------------------------------------------------------------- Holat

  let activePrizes = [];
  let currentWonPrize = null;   // g'alaba oynasida ko'rsatilgan (PENDING) sovg'a
  let userAvailableSpins = 0;
  let userReferralLink = '';
  let savedProfile = null;      // avval kiritilgan ism/telefon
  let telegramUser = null;
  let lastFriendCount = null;
  let spinsThisSession = 0;
  let submittingLead = false;

  // Server tekshiradigan shartlar — UI shunga qarab tugma holatini tanlaydi
  let subscription = { ok: true, channels: [] };
  let campaign = { state: 'active', message: '' };
  let dailyBonus = { enabled: false, available: false };
  let checkingSubscription = false;

  const WINNERS_PAGE_SIZE = 30;
  let winnersOffset = 0;
  let winnersLoaded = false;
  let winnersBusy = false;

  // ---------------------------------------------------------------- Yordamchilar

  function show(el) { if (el) el.classList.remove('hidden'); }
  function hide(el) { if (el) el.classList.add('hidden'); }

  function icon(name) {
    return `<svg class="icon"><use href="#i-${name}"/></svg>`;
  }

  function formatDateTime(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    const pad = (n) => String(n).padStart(2, '0');
    return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  /** "5 daqiqa oldin" ko'rinishidagi nisbiy vaqt */
  function timeAgo(iso) {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '';

    const seconds = Math.floor((Date.now() - d.getTime()) / 1000);
    if (seconds < 60) return 'hozir';

    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes} daq oldin`;

    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours} soat oldin`;

    const days = Math.floor(hours / 24);
    if (days < 7) return `${days} kun oldin`;

    return formatDateTime(iso).split(' ')[0];
  }

  function formatPhoneDigits(digits) {
    const parts = [digits.slice(0, 2), digits.slice(2, 5), digits.slice(5, 7), digits.slice(7, 9)];
    return parts.filter(Boolean).join(' ');
  }

  // Telegram titrash javobi — brauzerda va eski klientlarda jim o'tadi
  const hf = inTelegram && tgAtLeast('6.1') ? tg.HapticFeedback : null;
  const haptic = {
    impact(style = 'light') { try { hf?.impactOccurred(style); } catch (e) { /* */ } },
    notify(type) { try { hf?.notificationOccurred(type); } catch (e) { /* */ } },
    select() { try { hf?.selectionChanged(); } catch (e) { /* */ } },
  };

  // ---------------------------------------------------------------- Toast (alert() o'rniga)

  const toastStack = $('toast-stack');
  const TOAST_ICONS = { error: 'alert', success: 'check', info: 'gift' };

  function toast(message, type = 'error', ms = 3200) {
    if (!toastStack) return;
    if (type === 'error') haptic.notify('error');

    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.setAttribute('role', type === 'error' ? 'alert' : 'status');
    el.innerHTML = `${icon(TOAST_ICONS[type] || 'alert')}<span></span>`;
    el.querySelector('span').textContent = message;
    toastStack.appendChild(el);

    // Bir vaqtda 3 tadan ortiq ko'rinmasin
    while (toastStack.children.length > 3) toastStack.firstElementChild.remove();

    setTimeout(() => {
      el.classList.add('leaving');
      setTimeout(() => el.remove(), 260);
    }, ms);
  }

  // ---------------------------------------------------------------- Modallar + Telegram BackButton

  const modalStack = [];

  function onBackButton() {
    const top = modalStack[modalStack.length - 1];
    if (top) closeModal(top);
  }

  function syncBackButton() {
    if (!tg || !tg.BackButton || !tgAtLeast('6.1')) return;
    modalStack.length ? tg.BackButton.show() : tg.BackButton.hide();
  }

  if (tg && tg.BackButton && tgAtLeast('6.1')) {
    tg.BackButton.onClick(onBackButton);
  }

  function openModal(el) {
    if (!el || modalStack.includes(el)) return;
    modalStack.push(el);
    el.classList.add('active');
    document.body.style.overflow = 'hidden';
    syncBackButton();
    if (el === leadModal) showMainButton();
  }

  function closeModal(el) {
    const idx = modalStack.indexOf(el);
    if (idx !== -1) modalStack.splice(idx, 1);
    el.classList.remove('active');
    if (!modalStack.length) document.body.style.overflow = '';
    syncBackButton();
    if (el === leadModal) hideMainButton();
  }

  // Pastdan chiqadigan oynalar fonini bosganda yopiladi
  [leadModal, qrViewModal].forEach((overlay) => {
    overlay?.addEventListener('click', (e) => {
      if (e.target === overlay) closeModal(overlay);
    });
  });

  // ---------------------------------------------------------------- Telegram MainButton (forma uchun)

  const mainButton = inTelegram && tg.MainButton ? tg.MainButton : null;
  if (mainButton) document.body.classList.add('tg-main-button');

  function showMainButton() {
    if (!mainButton) return;
    mainButton.setParams({
      text: 'Yutuqni saqlash',
      color: '#7c6cf6',
      text_color: '#ffffff',
      is_active: true,
      is_visible: true,
    });
    mainButton.onClick(submitLead);
  }

  function hideMainButton() {
    if (!mainButton) return;
    mainButton.offClick(submitLead);
    mainButton.hideProgress();
    mainButton.hide();
  }

  // ---------------------------------------------------------------- Tab almashish

  const TAB_SUBTITLES = {
    spin: headerSubtitle ? headerSubtitle.innerText.trim() : '',
    history: 'Yutuqlarim',
    winners: "G'oliblar"
  };

  const tabButtons = document.querySelectorAll('.appbar-item');

  function switchTab(name) {
    document.querySelectorAll('.tab-view').forEach((view) => {
      view.classList.toggle('active', view.id === `view-${name}`);
    });

    tabButtons.forEach((btn) => {
      const isActive = btn.dataset.view === name;
      btn.classList.toggle('active', isActive);
      btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
    });

    if (headerSubtitle && TAB_SUBTITLES[name]) {
      headerSubtitle.innerText = TAB_SUBTITLES[name];
    }

    window.scrollTo({ top: 0, behavior: 'smooth' });

    // G'oliblar ro'yxatini faqat birinchi ochilganda yuklaymiz
    if (name === 'winners' && !winnersLoaded) {
      loadWinners(true);
    }
  }

  tabButtons.forEach((btn) => {
    btn.addEventListener('click', () => {
      if (!btn.classList.contains('active')) haptic.select();
      switchTab(btn.dataset.view);
    });
  });

  document.querySelectorAll('[data-goto]').forEach((btn) => {
    btn.addEventListener('click', () => switchTab(btn.dataset.goto));
  });

  // ---------------------------------------------------------------- Ovoz

  soundToggleBtn?.addEventListener('click', () => {
    rouletteEngine.soundEnabled = !rouletteEngine.soundEnabled;
    soundToggleBtn.classList.toggle('is-on', rouletteEngine.soundEnabled);
    soundToggleBtn.setAttribute('aria-label', rouletteEngine.soundEnabled ? "Ovozni o'chirish" : 'Ovozni yoqish');
    haptic.select();
  });

  // ---------------------------------------------------------------- Server holati

  /** validate-init / claim / my-prize javoblaridagi umumiy holatni UI'ga qo'llaydi */
  function applyUserState(data) {
    userAvailableSpins = data.available_spins || 0;
    userReferralLink = data.referral_link || userReferralLink || 'https://t.me/texnogiftbot';
    currentWonPrize = data.pending_prize || null;
    savedProfile = data.saved_profile || savedProfile;
    if (data.subscription) subscription = data.subscription;
    if (data.campaign) campaign = data.campaign;
    if (data.daily_bonus) dailyBonus = data.daily_bonus;

    if (spinsCountBadge) spinsCountBadge.innerText = userAvailableSpins;
    renderCampaign();
    renderSubscription();
    renderDailyBonus();
    updateSpinButton();
    updateReferralHub(data);
    renderHistory(data.winnings || []);
  }

  async function loadUserState() {
    const resp = await fetch('/api/validate-init/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ init_data: initDataRaw })
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    telegramUser = data.user_info || telegramUser;
    applyUserState(data);
    return data;
  }

  async function init() {
    loadPrizes();

    if (!initDataRaw) {
      showOutsideTelegram();
      return;
    }

    show(historyLoading);
    hide(historyEmpty);

    try {
      const data = await loadUserState();
      // Oldingi safar aylantirilgan, lekin rasmiylashtirilmagan sovg'a
      if (data.pending_prize) {
        setTimeout(() => openVictoryModal(data.pending_prize, { resumed: true }), 400);
      }
    } catch (err) {
      console.error('Initial check error:', err);
      renderHistory([]);
      setSpinButton('retry');
      toast("Server bilan bog'lanib bo'lmadi. Qayta urinib ko'ring.");
    } finally {
      hide(historyLoading);
    }
  }

  function showOutsideTelegram() {
    show(outsideTelegram);
    hide(spinBtn);
    hide(referralCard);
    hide(subscribeGate);
    hide(dailyBonusCard);
    if (spinsCountBadge) spinsCountBadge.innerText = '–';
    renderHistory([]);
  }

  async function loadPrizes() {
    try {
      const resp = await fetch('/api/prizes/');
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      activePrizes = await resp.json();

      if (activePrizes.length > 0) {
        rouletteEngine.populateTrack(activePrizes);
      } else {
        toast("Hozircha barabanda sovg'alar yo'q", 'info');
      }
    } catch (err) {
      console.error('Failed to load prizes:', err);
    }
  }

  // Foydalanuvchi do'stiga havola yuborib qaytganda progress yangilansin
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && initDataRaw && !rouletteEngine.isSpinning && !modalStack.length) {
      loadUserState().catch(() => { /* jim — keyingi safar yangilanadi */ });
    }
  });

  // ---------------------------------------------------------------- Asosiy tugma

  const SPIN_MODES = {
    loading: { text: 'Yuklanmoqda…', icon: 'gift', disabled: true },
    spinning: { text: 'Aylanmoqda…', icon: 'gift', disabled: true },
    spin: { text: "Sovg'ani ochish", icon: 'gift', pulse: true },
    claim: { text: 'Yutuqni rasmiylashtirish', icon: 'check', pulse: true },
    invite: { text: "Do'stlarni taklif qilish", icon: 'users', secondary: true },
    subscribe: { text: 'Obunani tekshirish', icon: 'refresh', pulse: true },
    checking: { text: 'Tekshirilmoqda…', icon: 'refresh', disabled: true },
    closed: { text: 'Aksiya yopiq', icon: 'lock', disabled: true, secondary: true },
    retry: { text: 'Qayta urinish', icon: 'refresh' },
  };

  let spinMode = 'loading';

  function setSpinButton(mode) {
    const cfg = SPIN_MODES[mode];
    spinMode = mode;
    spinBtn.disabled = !!cfg.disabled;
    spinBtn.classList.toggle('is-pulsing', !!cfg.pulse);
    spinBtn.classList.toggle('btn-primary', !cfg.secondary);
    spinBtn.classList.toggle('btn-secondary', !!cfg.secondary);
    spinBtnText.innerText = mode === 'spin' && userAvailableSpins > 1
      ? `${cfg.text} · ${userAvailableSpins}`
      : cfg.text;
    spinBtnIcon.innerHTML = `<use href="#i-${cfg.icon}"/>`;
  }

  function updateSpinButton() {
    if (rouletteEngine.isSpinning) return;
    // Tushgan sovg'ani rasmiylashtirish har doim mumkin — aksiya tugagan bo'lsa ham
    if (currentWonPrize) setSpinButton('claim');
    else if (campaign.state !== 'active') setSpinButton('closed');
    else if (!subscription.ok) setSpinButton(checkingSubscription ? 'checking' : 'subscribe');
    else if (userAvailableSpins > 0) setSpinButton('spin');
    else setSpinButton('invite');
  }

  spinBtn.addEventListener('click', () => {
    switch (spinMode) {
      case 'spin': return startSpin();
      case 'claim': return openVictoryModal(currentWonPrize, { resumed: true });
      case 'invite': return shareReferral();
      case 'subscribe': return checkSubscription();
      case 'retry':
        setSpinButton('loading');
        return init();
    }
  });

  async function startSpin() {
    if (rouletteEngine.isSpinning) return;
    if (!activePrizes.length) {
      toast("Sovg'alar hali yuklanmadi, bir oz kuting", 'info');
      loadPrizes();
      return;
    }

    haptic.impact('medium');
    setSpinButton('spinning');

    let data;
    try {
      const resp = await fetch('/api/spin/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ init_data: initDataRaw })
      });
      data = await resp.json();

      if (!resp.ok) {
        if (resp.status === 400 && data.available_spins === 0) userAvailableSpins = 0;
        if (data.code === 'not_subscribed' && data.subscription) {
          subscription = data.subscription;
          renderSubscription();
        }
        if (data.code === 'campaign_closed' && data.campaign) {
          campaign = data.campaign;
          renderCampaign();
          renderSubscription();
        }
        toast(data.error || 'Xatolik yuz berdi');
        updateSpinButton();
        return;
      }
    } catch (err) {
      console.error('Spin error:', err);
      toast("Server bilan bog'lanishda xatolik");
      updateSpinButton();
      return;
    }

    // Spin serverda sarflandi — oyna yopilsa ham sovg'a saqlanib qoladi
    currentWonPrize = data.prize;

    if (!data.is_new_spin) {
      // Avval aylantirilgan, rasmiylashtirilmagan sovg'a — animatsiyasiz ko'rsatamiz
      updateSpinButton();
      openVictoryModal(currentWonPrize, { resumed: true });
      return;
    }

    userAvailableSpins = Math.max(0, userAvailableSpins - 1);
    if (spinsCountBadge) spinsCountBadge.innerText = userAvailableSpins;

    // Birinchi aylantirish to'liq, keyingilari qisqaroq
    const duration = spinsThisSession === 0 ? 5000 : 3500;
    spinsThisSession += 1;

    rouletteEngine.spin(activePrizes, currentWonPrize, data.target_index || 65, (wonPrize) => {
      haptic.notify('success');
      updateSpinButton();
      openVictoryModal(wonPrize);
    }, duration);
  }

  // ---------------------------------------------------------------- G'alaba oynasi

  function openVictoryModal(prize, { resumed = false } = {}) {
    if (!prize) return;
    const info = rarityInfo(prize.rarity);

    victoryKicker.innerText = resumed ? 'Sizni kutayotgan sovg\'a' : 'Tabriklaymiz!';
    victoryPrizeTitle.innerText = prize.title || '';
    victoryRarity.innerText = info.label;
    victoryPrizeEmoji.innerText = info.icon;
    victoryPrizeBox.className = `reveal-inner rarity-${prize.rarity || 'COMMON'}`;

    const imageSrc = prize.display_image || prize.image_url || '';
    if (imageSrc) {
      victoryPrizeImg.onerror = () => hide(victoryPrizeImg);
      victoryPrizeImg.onload = () => { victoryPrizeEmoji.style.visibility = 'hidden'; };
      victoryPrizeEmoji.style.visibility = '';
      victoryPrizeImg.src = imageSrc;
      show(victoryPrizeImg);
    } else {
      victoryPrizeImg.removeAttribute('src');
      victoryPrizeEmoji.style.visibility = '';
      hide(victoryPrizeImg);
    }

    openModal(victoryModal);

    // Karta aylanib ochiladi, keyin konfetti
    setTimeout(() => {
      victoryPrizeBox.classList.add('flipped');
      haptic.impact(prize.rarity === 'LEGENDARY' ? 'heavy' : 'medium');
    }, resumed ? 150 : 450);

    setTimeout(() => celebrate(prize.rarity), resumed ? 600 : 1000);
  }

  function celebrate(rarity) {
    if (typeof window.confetti !== 'function') return;
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

    const legendary = rarity === 'LEGENDARY';
    const colors = legendary
      ? ['#fde047', '#eab308', '#fff7cc', '#f59e0b']
      : ['#7c6cf6', '#a855f7', '#ec4899', '#3b82f6', '#10b981'];

    const burst = (x, angle) => window.confetti({
      particleCount: legendary ? 90 : 50,
      spread: legendary ? 80 : 60,
      angle,
      startVelocity: legendary ? 55 : 45,
      origin: { x, y: 0.6 },
      colors,
      zIndex: 150,
      disableForReducedMotion: true,
    });

    burst(0.1, 60);
    burst(0.9, 120);
    if (legendary) setTimeout(() => { burst(0.5, 90); }, 350);
  }

  btnClaimVictory.addEventListener('click', () => {
    haptic.impact('light');
    // Konfetti forma ustida uchib, xalaqit bermasin
    if (typeof window.confetti?.reset === 'function') window.confetti.reset();
    closeModal(victoryModal);
    openLeadModal();
  });

  // ---------------------------------------------------------------- Forma

  function openLeadModal() {
    const phone = savedProfile && savedProfile.phone_digits;
    phoneError && hide(phoneError);
    inputPhone.classList.remove('is-invalid');
    inputFirstName.classList.remove('is-invalid');

    if (phone) {
      // Avval kiritilgan ma'lumotlar — faqat tasdiqlash kifoya
      inputFirstName.value = savedProfile.first_name || '';
      inputLastName.value = savedProfile.last_name || '';
      inputPhone.value = formatPhoneDigits(phone);
      savedName.innerText = `${savedProfile.first_name || ''} ${savedProfile.last_name || ''}`.trim();
      savedPhone.innerText = `+998 ${formatPhoneDigits(phone)}`;
      show(savedProfileBox);
      hide(profileFields);
    } else {
      if (!inputFirstName.value && telegramUser?.first_name) inputFirstName.value = telegramUser.first_name;
      if (!inputLastName.value && telegramUser?.last_name) inputLastName.value = telegramUser.last_name;
      hide(savedProfileBox);
      show(profileFields);
    }

    openModal(leadModal);
  }

  btnEditProfile?.addEventListener('click', () => {
    hide(savedProfileBox);
    show(profileFields);
    inputPhone.focus();
  });

  function getPhoneDigits() {
    return inputPhone.value.replace(/\D/g, '').slice(0, 9);
  }

  inputPhone.addEventListener('input', () => {
    let digits = inputPhone.value.replace(/\D/g, '');
    // Foydalanuvchi +998 yoki 998 bilan boshlab yozsa yoki nusxalasa — kesib tashlaymiz
    if (digits.startsWith('998') && digits.length > 9) digits = digits.slice(3);
    inputPhone.value = formatPhoneDigits(digits.slice(0, 9));
    if (getPhoneDigits().length === 9) {
      inputPhone.classList.remove('is-invalid');
      hide(phoneError);
    }
  });

  inputFirstName.addEventListener('input', () => inputFirstName.classList.remove('is-invalid'));

  leadForm.addEventListener('submit', (e) => {
    e.preventDefault();
    submitLead();
  });

  function setSubmitting(on) {
    submittingLead = on;
    btnSubmitLead.disabled = on;
    if (mainButton) {
      if (on) { mainButton.showProgress(false); mainButton.disable(); }
      else { mainButton.hideProgress(); mainButton.enable(); }
    }
  }

  async function submitLead() {
    if (submittingLead) return;

    if (!currentWonPrize) {
      toast("Rasmiylashtiriladigan sovg'a topilmadi");
      closeModal(leadModal);
      return;
    }

    const firstName = inputFirstName.value.trim();
    const phoneDigits = getPhoneDigits();

    if (!firstName || phoneDigits.length !== 9) {
      // Xato bo'lsa, maydonlarni ko'rsatamiz
      hide(savedProfileBox);
      show(profileFields);
      if (!firstName) inputFirstName.classList.add('is-invalid');
      if (phoneDigits.length !== 9) {
        inputPhone.classList.add('is-invalid');
        show(phoneError);
      }
      haptic.notify('error');
      (!firstName ? inputFirstName : inputPhone).focus();
      return;
    }

    setSubmitting(true);

    try {
      const resp = await fetch('/api/claim-prize/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          init_data: initDataRaw,
          first_name: firstName,
          last_name: inputLastName.value.trim(),
          phone_number: '+998' + phoneDigits
        })
      });
      const data = await resp.json();

      if (!resp.ok) {
        toast(data.error || "Ma'lumotlarni saqlashda xatolik");
        // Server holati o'zgargan bo'lishi mumkin (masalan, boshqa qurilmada rasmiylashtirilgan)
        if (resp.status === 400) {
          closeModal(leadModal);
          loadUserState().catch(() => {});
        }
        return;
      }

      closeModal(leadModal);
      applyUserState(data);
      haptic.notify('success');
      toast("Yutuq saqlandi! QR-kodingiz tayyor", 'success');

      // Yangi yutuq g'oliblar ro'yxatiga ham qo'shildi — keyingi ochilishda yangilansin
      winnersLoaded = false;

      switchTab('history');
      if (data.winning_result) {
        setTimeout(() => openQRModal(data.winning_result), 350);
      }

    } catch (err) {
      console.error('Claim prize error:', err);
      toast("Serverga saqlashda xatolik yuz berdi");
    } finally {
      setSubmitting(false);
    }
  }

  // ---------------------------------------------------------------- Tab 2: yutuqlarim

  const STATUS_LABELS = {
    ACTIVE: 'Aktiv',
    USED: 'Berilgan',
    EXPIRED: "Muddati o'tgan"
  };

  function prizeThumb(prize, className) {
    const info = rarityInfo(prize.rarity);
    const src = prize.display_image || prize.image_url || '';
    return `
      <div class="${className}">
        <span>${info.icon}</span>
        ${src ? `<img src="${escapeHTML(src)}" alt="" loading="lazy" onerror="this.remove()">` : ''}
      </div>`;
  }

  function renderHistory(winnings) {
    const list = Array.isArray(winnings) ? winnings : [];
    historyList.innerHTML = '';

    // Appbar'dagi qizil belgi — faqat aktiv (hali olinmagan) yutuqlar soni
    const activeCount = list.filter((w) => w.status === 'ACTIVE').length;
    historyBadge.innerText = activeCount;
    activeCount > 0 ? show(historyBadge) : hide(historyBadge);

    if (list.length === 0) {
      show(historyEmpty);
      return;
    }
    hide(historyEmpty);

    list.forEach((w) => {
      const prize = w.prize || {};
      const status = w.status || 'ACTIVE';
      const isActive = status === 'ACTIVE';

      const when = isActive
        ? `${formatDateTime(w.expires_at)} gacha`
        : status === 'USED'
          ? formatDateTime(w.used_at)
          : formatDateTime(w.expires_at);

      const card = document.createElement('div');
      card.className = `win-card rarity-${escapeHTML(prize.rarity)}${isActive ? '' : ' is-inactive'}`;
      card.innerHTML = `
        ${prizeThumb(prize, 'win-thumb')}
        <div class="win-body">
          <div class="win-title">${escapeHTML(prize.title || '')}</div>
          <div class="win-meta">
            <span class="status-chip ${escapeHTML(status)}">${escapeHTML(STATUS_LABELS[status] || status)}</span>
            <span class="win-code">${escapeHTML(w.promo_code || '')}</span>
          </div>
          <div class="win-meta">${escapeHTML(when)}</div>
        </div>
        ${isActive ? `<button class="btn btn-secondary btn-qr" type="button">${icon('qr')} QR</button>` : ''}
      `;

      if (isActive) {
        card.querySelector('.btn-qr').addEventListener('click', () => {
          haptic.impact('light');
          openQRModal(w);
        });
      }

      historyList.appendChild(card);
    });
  }

  // ---------------------------------------------------------------- Tab 3: g'oliblar

  async function loadWinners(reset) {
    if (winnersBusy) return;
    winnersBusy = true;

    if (reset) {
      winnersOffset = 0;
      winnersList.innerHTML = '';
      show(winnersLoading);
      hide(winnersEmpty);
      hide(winnersError);
      hide(winnersTotal);
      hide(btnLoadMoreWinners);
    } else {
      btnLoadMoreWinners.disabled = true;
      btnLoadMoreWinners.innerText = 'Yuklanmoqda…';
    }

    try {
      const url = `/api/winners/?limit=${WINNERS_PAGE_SIZE}&offset=${winnersOffset}`;
      const resp = await fetch(url);

      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

      const data = await resp.json();
      const winners = data.winners || [];

      winners.forEach((w, i) => {
        winnersList.appendChild(buildWinnerRow(w, winnersOffset + i + 1));
      });

      winnersOffset += winners.length;
      winnersLoaded = true;

      if (data.total > 0) {
        winnersTotalCount.innerText = data.total;
        show(winnersTotal);
      }

      winnersOffset === 0 ? show(winnersEmpty) : hide(winnersEmpty);
      data.has_more ? show(btnLoadMoreWinners) : hide(btnLoadMoreWinners);

    } catch (err) {
      console.error('Winners load error:', err);
      if (winnersOffset === 0) {
        show(winnersError);
      } else {
        toast("Ro'yxatning davomini yuklab bo'lmadi");
      }
    } finally {
      hide(winnersLoading);
      btnLoadMoreWinners.disabled = false;
      btnLoadMoreWinners.innerText = "Yana ko'rsatish";
      winnersBusy = false;
    }
  }

  function buildWinnerRow(w, rank) {
    const row = document.createElement('div');
    row.className = `winner-row rarity-${escapeHTML(w.prize_rarity)}`;

    const medal = rank === 1 ? '🥇' : rank === 2 ? '🥈' : rank === 3 ? '🥉' : rank;

    row.innerHTML = `
      <div class="winner-rank">${escapeHTML(medal)}</div>
      ${prizeThumb({ rarity: w.prize_rarity, display_image: w.prize_image }, 'winner-thumb')}
      <div class="winner-body">
        <div class="winner-name">${escapeHTML(w.display_name)}</div>
        <div class="winner-prize">${escapeHTML(w.prize_title || '')}</div>
      </div>
      <div class="winner-time">${escapeHTML(timeAgo(w.created_at))}</div>
    `;
    return row;
  }

  btnLoadMoreWinners.addEventListener('click', () => loadWinners(false));
  btnRetryWinners.addEventListener('click', () => loadWinners(true));

  // ---------------------------------------------------------------- QR oynasi

  /** Joriy oynada ochilgan sovg'aning Google Maps havolasi */
  let currentMapLink = '';

  function openQRModal(winning) {
    const prize = winning.prize || {};
    const promoCode = winning.promo_code || '';

    qrModalTitle.innerText = prize.title || '';
    qrModalPromocode.innerText = promoCode;
    qrModalQrcode.innerHTML = '';

    renderPickupLocation(prize);

    if (window.QRCode) {
      new QRCode(qrModalQrcode, {
        text: promoCode,
        width: 190,
        height: 190,
        colorDark: '#000000',
        colorLight: '#ffffff',
        correctLevel: QRCode.CorrectLevel.H
      });
    } else {
      qrModalQrcode.innerHTML =
        `<img src="https://api.qrserver.com/v1/create-qr-code/?size=190x190&data=${encodeURIComponent(promoCode)}" alt="QR" width="190" height="190">`;
    }

    openModal(qrViewModal);
  }

  /**
   * Sovg'ani olish manzilini QR ostida ko'rsatadi.
   * Manzil va koordinata admin paneldan kiritiladi; ikkalasi ham bo'sh
   * bo'lsa blok butunlay yashiriladi.
   */
  function renderPickupLocation(prize) {
    const address = (prize.pickup_address || '').trim();
    currentMapLink = prize.map_link || '';

    if (!address && !currentMapLink) {
      hide(qrLocation);
      hide(btnOpenMap);
      return;
    }

    qrLocationAddress.innerText = address || "Manzilni xaritada ko'ring";
    show(qrLocation);
    currentMapLink ? show(btnOpenMap) : hide(btnOpenMap);
  }

  btnOpenMap.addEventListener('click', () => {
    if (!currentMapLink) return;
    if (tg && tg.openLink) tg.openLink(currentMapLink);
    else window.open(currentMapLink, '_blank');
  });

  btnCloseQrModal.addEventListener('click', () => closeModal(qrViewModal));

  // ---------------------------------------------------------------- Referal

  function updateReferralHub(data) {
    const perSpin = data.referrals_per_spin || 3;
    const invited = data.invited_count || 0;
    const friends = Array.isArray(data.referral_friends) ? data.referral_friends : [];

    const pending = data.pending_invites || 0;

    refLinkInput.value = userReferralLink;
    invitedCountBadge.innerText = invited;
    pendingInvitesCount.innerText = pending;
    pending > 0 ? show(pendingInvites) : hide(pendingInvites);
    referralTitle.textContent = `${perSpin} do'st = +1 imkoniyat`;
    friendSlots.style.gridTemplateColumns = `repeat(${Math.min(perSpin, 5)}, 1fr)`;

    // Yangi qo'shilgan do'st joyi "sakrab" to'ladi
    const newlyAdded = lastFriendCount !== null && invited > lastFriendCount;
    lastFriendCount = invited;

    friendSlots.innerHTML = '';
    for (let i = 0; i < perSpin; i++) {
      const slot = document.createElement('div');
      const name = friends[i];
      if (name) {
        slot.className = 'friend-slot filled' + (newlyAdded && i === friends.length - 1 ? ' pop' : '');
        slot.textContent = (name.trim()[0] || '?').toUpperCase();
        slot.title = name;
      } else {
        slot.className = 'friend-slot';
        slot.innerHTML = icon('plus');
      }
      friendSlots.appendChild(slot);
    }

    const remaining = perSpin - friends.length;
    referralHint.textContent = friends.length === 0
      ? `Havolangiz orqali ${perSpin} ta do'stingiz yutug'ini olsa, sovg'ani yana bir marta ochasiz`
      : `Zo'r! Yana ${remaining} ta do'st — va sovg'ani yana bir marta ochasiz`;

    if (newlyAdded) {
      haptic.notify('success');
      toast("Do'stingiz hisobga qo'shildi!", 'success', 2400);
    }
  }

  function shareReferral() {
    haptic.impact('light');
    const link = refLinkInput.value || userReferralLink;
    const shareText = encodeURIComponent(
      "🎁 Yoshlar Texnoparki Gift Box barabanida ishtirok eting va qimmatbaho yutuqlarni yutib oling!"
    );
    const shareUrl = `https://t.me/share/url?url=${encodeURIComponent(link)}&text=${shareText}`;

    if (tg && tg.openTelegramLink) tg.openTelegramLink(shareUrl);
    else window.open(shareUrl, '_blank');
  }

  btnShareTg.addEventListener('click', shareReferral);

  btnCopyRef.addEventListener('click', async () => {
    const link = refLinkInput.value || userReferralLink;
    try {
      await navigator.clipboard.writeText(link);
    } catch (e) {
      refLinkInput.select();
      document.execCommand('copy');
    }
    haptic.notify('success');
    toast('Havola nusxalandi', 'success', 2000);
  });

  // ---------------------------------------------------------------- Aksiya muddati

  function renderCampaign() {
    if (campaign.state === 'active' || !campaign.message) {
      hide(campaignBanner);
      return;
    }
    campaignMessage.textContent = campaign.message;
    show(campaignBanner);
  }

  // ---------------------------------------------------------------- Majburiy obuna

  function openChannel(link) {
    if (!link) return;
    haptic.impact('light');
    if (tg && tg.openTelegramLink && link.startsWith('https://t.me/')) tg.openTelegramLink(link);
    else if (tg && tg.openLink) tg.openLink(link);
    else window.open(link, '_blank');
  }

  function renderSubscription() {
    // Sovg'a kutib turgan yoki aksiya yopiq bo'lsa, obuna so'rashning ma'nosi yo'q
    const needed = !subscription.ok && !currentWonPrize && campaign.state === 'active' && !!initDataRaw;
    if (!needed) {
      hide(subscribeGate);
      return;
    }

    subscribeChannels.innerHTML = '';
    (subscription.channels || []).forEach((ch) => {
      const row = document.createElement('div');
      row.className = 'channel-row' + (ch.subscribed ? ' is-joined' : '');

      const title = document.createElement('span');
      title.className = 'channel-title';
      title.textContent = ch.title;
      row.appendChild(title);

      if (ch.subscribed) {
        const ok = document.createElement('span');
        ok.className = 'channel-status';
        ok.innerHTML = icon('check');
        ok.setAttribute('aria-label', "Obuna bo'lingan");
        row.appendChild(ok);
      } else {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn btn-telegram';
        btn.innerHTML = `${icon('external')}<span>Obuna bo'lish</span>`;
        btn.disabled = !ch.link;
        btn.addEventListener('click', () => openChannel(ch.link));
        row.appendChild(btn);
      }
      subscribeChannels.appendChild(row);
    });
    show(subscribeGate);
  }

  async function checkSubscription() {
    if (checkingSubscription) return;
    checkingSubscription = true;
    updateSpinButton();

    try {
      const resp = await fetch('/api/check-subscription/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ init_data: initDataRaw })
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      subscription = await resp.json();

      if (subscription.ok) {
        haptic.notify('success');
        toast("Rahmat! Endi barabanni aylantirishingiz mumkin", 'success');
      } else {
        toast("Hali barcha kanallarga obuna bo'lmagansiz");
      }
    } catch (err) {
      console.error('Subscription check error:', err);
      toast("Obunani tekshirib bo'lmadi. Qayta urinib ko'ring.");
    } finally {
      checkingSubscription = false;
      renderSubscription();
      updateSpinButton();
    }
  }

  // ---------------------------------------------------------------- Kunlik bonus

  function renderDailyBonus() {
    dailyBonus.enabled && dailyBonus.available && initDataRaw ? show(dailyBonusCard) : hide(dailyBonusCard);
  }

  btnDailyBonus.addEventListener('click', async () => {
    btnDailyBonus.disabled = true;
    try {
      const resp = await fetch('/api/daily-bonus/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ init_data: initDataRaw })
      });
      const data = await resp.json();
      if (!resp.ok) {
        toast(data.error || 'Xatolik yuz berdi');
        dailyBonus.available = false;
        renderDailyBonus();
        return;
      }
      haptic.notify('success');
      toast(data.message || "+1 aylantirish qo'shildi!", 'success');
      applyUserState(data);
    } catch (err) {
      console.error('Daily bonus error:', err);
      toast("Server bilan bog'lanishda xatolik");
    } finally {
      btnDailyBonus.disabled = false;
    }
  });

  // ---------------------------------------------------------------- Top taklifchilar

  const boardButtons = document.querySelectorAll('.segmented-item');
  const BOARD_SUBTITLES = {
    winners: "Shu botda sovg'a yutib olgan ishtirokchilar",
    referrers: "Eng ko'p do'st taklif qilgan ishtirokchilar",
  };

  function switchBoard(name) {
    boardButtons.forEach((btn) => {
      const isActive = btn.dataset.board === name;
      btn.classList.toggle('active', isActive);
      btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
    });
    name === 'winners' ? show(boardWinners) : hide(boardWinners);
    name === 'referrers' ? show(boardReferrers) : hide(boardReferrers);
    winnersSubtitle.textContent = BOARD_SUBTITLES[name];
    if (name === 'referrers') loadReferrers();
  }

  boardButtons.forEach((btn) => {
    btn.addEventListener('click', () => {
      if (!btn.classList.contains('active')) haptic.select();
      switchBoard(btn.dataset.board);
    });
  });

  async function loadReferrers() {
    if (!referrersList.children.length) show(referrersLoading);
    hide(referrersEmpty);
    try {
      const resp = await fetch('/api/top-referrers/');
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      const rows = data.referrers || [];

      referrersList.innerHTML = '';
      rows.forEach((r) => {
        const row = document.createElement('div');
        row.className = 'winner-row';
        const medal = r.rank === 1 ? '🥇' : r.rank === 2 ? '🥈' : r.rank === 3 ? '🥉' : r.rank;
        row.innerHTML = `
          <div class="winner-rank">${escapeHTML(medal)}</div>
          <div class="winner-body">
            <div class="winner-name">${escapeHTML(r.display_name)}</div>
          </div>
          <div class="referrer-count">${escapeHTML(r.invited)} do'st</div>
        `;
        referrersList.appendChild(row);
      });
      rows.length ? hide(referrersEmpty) : show(referrersEmpty);
    } catch (err) {
      console.error('Referrers load error:', err);
      toast("Reytingni yuklab bo'lmadi");
    } finally {
      hide(referrersLoading);
    }
  }

  // ---------------------------------------------------------------- Start

  init();
});
