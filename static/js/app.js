/**
 * Telegram WebApp Integration & Main UI Controller
 *
 * Uchta bo'lim (pastki appbar orqali):
 *   1. spin    — baraban
 *   2. history — foydalanuvchining o'z yutuqlari va QR-kodlari
 *   3. winners — shu botda yutuq olganlarning umumiy ro'yxati
 */

document.addEventListener('DOMContentLoaded', () => {
  // Telegram WebApp SDK Initialization
  const tg = window.Telegram?.WebApp;
  if (tg) {
    tg.ready();
    tg.expand();
  }

  // Get raw initData or dev mock fallback
  const getInitData = () => {
    if (tg && tg.initData && tg.initData.trim() !== '') {
      return tg.initData;
    }
    return 'mock_123456789_Oquvchi';
  };

  const initDataRaw = getInitData();

  // ---------------------------------------------------------------- DOM

  const spinBtn = document.getElementById('spin-btn');
  const spinBtnText = document.getElementById('spin-btn-text');
  const soundToggleBtn = document.getElementById('sound-toggle');
  const headerSubtitle = document.getElementById('header-subtitle');

  // Grand Victory Modal Elements
  const victoryModal = document.getElementById('victory-modal');
  const victoryPrizeBox = document.getElementById('victory-prize-box');
  const victoryPrizeImg = document.getElementById('victory-prize-img');
  const victoryPrizeTitle = document.getElementById('victory-prize-title');
  const btnClaimVictory = document.getElementById('btn-claim-victory');

  // Lead Form Modal Elements
  const leadModal = document.getElementById('lead-modal');
  const leadForm = document.getElementById('lead-form');
  const inputFirstName = document.getElementById('input-first-name');
  const inputLastName = document.getElementById('input-last-name');
  const inputPhone = document.getElementById('input-phone');

  // Referral Elements
  const refLinkInput = document.getElementById('ref-link-input');
  const btnCopyRef = document.getElementById('btn-copy-ref');
  const btnShareTg = document.getElementById('btn-share-tg');
  const invitedCountBadge = document.getElementById('invited-count-badge');
  const spinsCountBadge = document.getElementById('spins-count-badge');
  const refProgressText = document.getElementById('ref-progress-text');
  const refProgressFill = document.getElementById('ref-progress-fill');

  // Tab 2 — Yutuqlar tarixi
  const historyList = document.getElementById('history-list');
  const historyEmpty = document.getElementById('history-empty');
  const historyLoading = document.getElementById('history-loading');
  const historyBadge = document.getElementById('history-badge');

  // Tab 3 — G'oliblar
  const winnersList = document.getElementById('winners-list');
  const winnersLoading = document.getElementById('winners-loading');
  const winnersEmpty = document.getElementById('winners-empty');
  const winnersError = document.getElementById('winners-error');
  const winnersTotal = document.getElementById('winners-total');
  const winnersTotalCount = document.getElementById('winners-total-count');
  const btnLoadMoreWinners = document.getElementById('btn-load-more-winners');
  const btnRetryWinners = document.getElementById('btn-retry-winners');

  // QR Viewer Modal Elements
  const qrViewModal = document.getElementById('qr-view-modal');
  const qrModalTitle = document.getElementById('qr-modal-title');
  const qrModalQrcode = document.getElementById('qr-modal-qrcode');
  const qrModalPromocode = document.getElementById('qr-modal-promocode');
  const btnCloseQrModal = document.getElementById('btn-close-qr-modal');
  const qrLocation = document.getElementById('qr-location');
  const qrLocationAddress = document.getElementById('qr-location-address');
  const btnOpenMap = document.getElementById('btn-open-map');

  // Instantiate CS2 Roulette Engine
  const rouletteEngine = new CS2RouletteEngine('roulette-track', 'roulette-viewport');

  let activePrizes = [];
  let currentWonPrize = null;
  let userAvailableSpins = 0;
  let userReferralLink = '';
  let myWinnings = [];

  // G'oliblar ro'yxati sahifalash holati
  const WINNERS_PAGE_SIZE = 30;
  let winnersOffset = 0;
  let winnersLoaded = false;
  let winnersBusy = false;

  // ---------------------------------------------------------------- Yordamchilar

  const RARITY_ICONS = {
    LEGENDARY: '🏆',
    EPIC: '💎',
    RARE: '🎁',
    COMMON: '⭐'
  };

  function rarityIcon(rarity) {
    return RARITY_ICONS[rarity] || '⭐';
  }

  /** XSS oldini olish uchun — innerHTML ga tushadigan har qanday matn shu yerdan o'tadi */
  function escapeHTML(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function show(el) { if (el) el.classList.remove('hidden'); }
  function hide(el) { if (el) el.classList.add('hidden'); }

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

  // ---------------------------------------------------------------- Tab almashish

  // Baraban bo'limining matni HTML'dan olinadi — shunda sarlavhani
  // faqat index.html ichida o'zgartirish yetarli bo'ladi.
  const TAB_SUBTITLES = {
    spin: headerSubtitle ? headerSubtitle.innerText.trim() : '',
    history: 'Sizning yutuqlaringiz',
    winners: 'Yutuq olganlar ro\'yxati'
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
    btn.addEventListener('click', () => switchTab(btn.dataset.view));
  });

  // Bo'sh holatdagi "Barabanga o'tish" tugmalari
  document.querySelectorAll('[data-goto]').forEach((btn) => {
    btn.addEventListener('click', () => switchTab(btn.dataset.goto));
  });

  // ---------------------------------------------------------------- Ovoz

  if (soundToggleBtn) {
    soundToggleBtn.addEventListener('click', () => {
      rouletteEngine.soundEnabled = !rouletteEngine.soundEnabled;
      if (rouletteEngine.soundEnabled) {
        soundToggleBtn.classList.add('active');
        soundToggleBtn.innerHTML = '🔊';
      } else {
        soundToggleBtn.classList.remove('active');
        soundToggleBtn.innerHTML = '🔇';
      }
    });
  }

  // ---------------------------------------------------------------- Boshlang'ich holat

  async function checkInitialUserStatus() {
    show(historyLoading);
    hide(historyEmpty);

    try {
      const resp = await fetch('/api/validate-init/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ init_data: initDataRaw })
      });
      const data = await resp.json();

      if (resp.ok) {
        userAvailableSpins = data.available_spins || 0;
        userReferralLink = data.referral_link || 'https://t.me/texnogiftbot';

        updateSpinButtonUI();
        updateReferralHub(userReferralLink, data.invited_count || 0, userAvailableSpins, data.referrals_per_spin);
        renderHistory(data.winnings || []);

        if (data.user_info) {
          if (data.user_info.first_name) inputFirstName.value = data.user_info.first_name;
          if (data.user_info.last_name) inputLastName.value = data.user_info.last_name;
        }
      } else {
        renderHistory([]);
      }

      await loadPrizes();

    } catch (err) {
      console.error('Initial check error:', err);
      renderHistory([]);
      await loadPrizes();
    } finally {
      hide(historyLoading);
    }
  }

  async function loadPrizes() {
    try {
      const resp = await fetch('/api/prizes/');
      activePrizes = await resp.json();

      if (activePrizes && activePrizes.length > 0) {
        rouletteEngine.populateTrack(activePrizes);
      }
    } catch (err) {
      console.error('Failed to load prizes:', err);
    }
  }

  function updateSpinButtonUI() {
    if (userAvailableSpins > 0) {
      spinBtn.disabled = false;
      spinBtnText.innerText = `🔑 Keysni Ochish (Imkoniyat: ${userAvailableSpins})`;
    } else {
      spinBtn.disabled = true;
      spinBtnText.innerText = `🔒 Imkoniyat Qolmagan (Do'stlarni Taklif Qiling)`;
    }
  }

  function updateReferralHub(refLink, invitedCount, spinsCount, perSpin) {
    if (refLinkInput) refLinkInput.value = refLink;
    if (invitedCountBadge) invitedCountBadge.innerText = invitedCount;
    if (spinsCountBadge) spinsCountBadge.innerText = spinsCount;

    // Har perSpin ta do'st = +1 aylantirish; progress keyingi bonusgacha
    const step = perSpin || 3;
    const progress = invitedCount % step;
    if (refProgressText) refProgressText.innerText = `${progress}/${step}`;
    if (refProgressFill) refProgressFill.style.width = `${(progress / step) * 100}%`;
  }

  // ---------------------------------------------------------------- Spin

  if (spinBtn) {
    spinBtn.addEventListener('click', async () => {
      if (rouletteEngine.isSpinning) return;
      if (userAvailableSpins <= 0) {
        alert("Sizda aylantirish imkoniyati qolmagan! Do'stlaringizni taklif qiling.");
        return;
      }

      spinBtn.disabled = true;
      spinBtnText.innerText = `Aylantirilmoqda...`;

      try {
        const resp = await fetch('/api/spin/', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ init_data: initDataRaw })
        });
        const data = await resp.json();

        if (!resp.ok) {
          alert(data.error || 'Xatolik yuz berdi');
          updateSpinButtonUI();
          return;
        }

        currentWonPrize = data.prize;
        const targetIndex = data.target_index || 65;

        // CS2 5s deceleration animation
        rouletteEngine.spin(activePrizes, currentWonPrize, targetIndex, (wonPrize) => {
          openVictoryModal(wonPrize);
        });

      } catch (err) {
        console.error('Spin error:', err);
        alert("Server bilan bog'lanishda xatolik");
        updateSpinButtonUI();
      }
    });
  }

  // ---------------------------------------------------------------- Victory modal

  function openVictoryModal(prize) {
    victoryPrizeTitle.innerText = prize.title;
    victoryPrizeBox.className = `victory-prize-display rarity-${prize.rarity}`;
    victoryPrizeBox.style.borderColor = prize.hex_color || '#3b82f6';
    victoryPrizeBox.style.boxShadow = `0 0 45px ${prize.hex_color || '#3b82f6'}`;

    // display_image — yuklangan fayl yoki tashqi URL (nisbiy yo'l ham bo'lishi mumkin)
    const imageSrc = prize.display_image || prize.image_url || '';

    if (imageSrc) {
      victoryPrizeImg.src = imageSrc;
      victoryPrizeImg.style.display = 'block';
      // Rasm yuklanmasa rasmni yashiramiz, sarlavha qoladi
      victoryPrizeImg.onerror = () => { victoryPrizeImg.style.display = 'none'; };
    } else {
      victoryPrizeImg.removeAttribute('src');
      victoryPrizeImg.style.display = 'none';
    }

    victoryModal.classList.add('active');
  }

  function closeVictoryModal() {
    victoryModal.classList.remove('active');
  }

  if (btnClaimVictory) {
    btnClaimVictory.addEventListener('click', () => {
      closeVictoryModal();
      openLeadModal();
    });
  }

  // ---------------------------------------------------------------- Lead forma

  function openLeadModal() {
    leadModal.classList.add('active');
  }

  function closeLeadModal() {
    leadModal.classList.remove('active');
  }

  // Telefon: foydalanuvchi faqat 9 ta raqam kiritadi, +998 prefiks doim turadi
  function formatPhoneDigits(digits) {
    const parts = [digits.slice(0, 2), digits.slice(2, 5), digits.slice(5, 7), digits.slice(7, 9)];
    return parts.filter(Boolean).join(' ');
  }

  function getPhoneDigits() {
    return inputPhone ? inputPhone.value.replace(/\D/g, '').slice(0, 9) : '';
  }

  if (inputPhone) {
    inputPhone.addEventListener('input', () => {
      let digits = inputPhone.value.replace(/\D/g, '');
      // Foydalanuvchi +998 yoki 998 bilan boshlab yozsa yoki nusxalasa — kesib tashlaymiz
      if (digits.startsWith('998')) digits = digits.slice(3);
      inputPhone.value = formatPhoneDigits(digits.slice(0, 9));
    });
  }

  if (leadForm) {
    leadForm.addEventListener('submit', async (e) => {
      e.preventDefault();

      if (!currentWonPrize) {
        alert("Yutib olingan sovg'a topilmadi!");
        return;
      }

      const phoneDigits = getPhoneDigits();
      if (phoneDigits.length !== 9) {
        alert("Telefon raqamini to'liq kiriting: +998 dan keyin 9 ta raqam");
        if (inputPhone) inputPhone.focus();
        return;
      }

      const submitBtn = leadForm.querySelector('button[type="submit"]');
      if (submitBtn) submitBtn.disabled = true;

      const payload = {
        init_data: initDataRaw,
        prize_id: currentWonPrize.id,
        first_name: inputFirstName.value.trim(),
        last_name: inputLastName.value.trim(),
        phone_number: '+998' + phoneDigits
      };

      try {
        const resp = await fetch('/api/claim-prize/', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await resp.json();

        if (!resp.ok) {
          alert(data.error || "Ma'lumotlarni saqlashda xatolik");
          return;
        }

        closeLeadModal();

        userAvailableSpins = data.available_spins || 0;
        userReferralLink = data.referral_link || userReferralLink;

        updateSpinButtonUI();
        updateReferralHub(userReferralLink, data.invited_count || 0, userAvailableSpins, data.referrals_per_spin);
        renderHistory(data.winnings || []);

        // Yangi yutuq g'oliblar ro'yxatiga ham qo'shildi — keyingi ochilishda yangilansin
        winnersLoaded = false;

        // Foydalanuvchini to'g'ridan-to'g'ri QR-kodi turgan bo'limga olib o'tamiz
        switchTab('history');

      } catch (err) {
        console.error('Claim prize error:', err);
        alert('Serverga saqlashda xatolik yuz berdi');
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    });
  }

  // ---------------------------------------------------------------- Tab 2: tarix

  const STATUS_LABELS = {
    ACTIVE: 'Aktiv',
    USED: 'Berilgan',
    EXPIRED: "Muddati o'tgan"
  };

  function renderHistory(winnings) {
    myWinnings = Array.isArray(winnings) ? winnings : [];

    if (!historyList) return;
    historyList.innerHTML = '';

    // Appbar'dagi qizil belgi — faqat aktiv (hali olinmagan) yutuqlar soni
    const activeCount = myWinnings.filter((w) => w.status === 'ACTIVE').length;
    if (historyBadge) {
      historyBadge.innerText = activeCount;
      activeCount > 0 ? show(historyBadge) : hide(historyBadge);
    }

    if (myWinnings.length === 0) {
      show(historyEmpty);
      return;
    }
    hide(historyEmpty);

    myWinnings.forEach((w) => {
      const prize = w.prize || {};
      const status = w.status || 'ACTIVE';
      const canShowQR = status === 'ACTIVE';

      const card = document.createElement('div');
      card.className = 'winning-item-card';

      const expiresText = status === 'ACTIVE'
        ? `Amal qiladi: ${formatDateTime(w.expires_at)}`
        : status === 'USED'
          ? `Berilgan: ${formatDateTime(w.used_at)}`
          : `Muddati tugagan: ${formatDateTime(w.expires_at)}`;

      card.innerHTML = `
        <div class="winning-item-info">
          <div class="winning-item-badge rarity-${escapeHTML(prize.rarity)}"
               style="color:${escapeHTML(prize.hex_color || '#3b82f6')}; border:1px solid ${escapeHTML(prize.hex_color || '#3b82f6')}">
            ${escapeHTML(prize.rarity || '')}
          </div>
          <div>
            <div class="winning-item-title">${escapeHTML(prize.title || '')}</div>
            <div class="winning-item-code">${escapeHTML(w.promo_code || '')}</div>
            <div class="history-meta">
              <span class="status-chip ${escapeHTML(status)}">${escapeHTML(STATUS_LABELS[status] || status)}</span>
              <span style="margin-left:.35rem">${escapeHTML(expiresText)}</span>
            </div>
          </div>
        </div>
        <button class="btn-view-qr" ${canShowQR ? '' : 'disabled'}>
          ${canShowQR ? '📱 QR-kod' : '—'}
        </button>
      `;

      if (canShowQR) {
        card.querySelector('.btn-view-qr').addEventListener('click', () => {
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

      if (winnersOffset === 0) {
        show(winnersEmpty);
      } else {
        hide(winnersEmpty);
      }

      data.has_more ? show(btnLoadMoreWinners) : hide(btnLoadMoreWinners);

    } catch (err) {
      console.error('Winners load error:', err);
      if (winnersOffset === 0) {
        show(winnersError);
      } else {
        alert("Ro'yxatning davomini yuklab bo'lmadi.");
      }
    } finally {
      hide(winnersLoading);
      btnLoadMoreWinners.disabled = false;
      btnLoadMoreWinners.innerText = 'Yana ko\'rsatish';
      winnersBusy = false;
    }
  }

  function buildWinnerRow(w, rank) {
    const row = document.createElement('div');
    row.className = 'winner-row';
    row.style.borderLeftColor = w.prize_color || '#3b82f6';

    const medal = rank === 1 ? '🥇' : rank === 2 ? '🥈' : rank === 3 ? '🥉' : rank;
    const img = w.prize_image
      ? `<img src="${escapeHTML(w.prize_image)}" alt="" onerror="this.remove()">`
      : '';

    row.innerHTML = `
      <div class="winner-rank">${escapeHTML(medal)}</div>
      <div class="winner-thumb">
        <span>${rarityIcon(w.prize_rarity)}</span>
        ${img}
      </div>
      <div class="winner-body">
        <div class="winner-name">${escapeHTML(w.display_name)}</div>
        <div class="winner-prize">${escapeHTML(w.prize_title || '')}</div>
      </div>
      <div class="winner-time">${escapeHTML(timeAgo(w.created_at))}</div>
    `;
    return row;
  }

  if (btnLoadMoreWinners) {
    btnLoadMoreWinners.addEventListener('click', () => loadWinners(false));
  }

  if (btnRetryWinners) {
    btnRetryWinners.addEventListener('click', () => loadWinners(true));
  }

  // ---------------------------------------------------------------- QR modal

  /** Joriy modalda ochilgan sovg'aning Google Maps havolasi */
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
        width: 180,
        height: 180,
        colorDark: '#000000',
        colorLight: '#ffffff',
        correctLevel: QRCode.CorrectLevel.H
      });
    } else {
      qrModalQrcode.innerHTML =
        `<img src="https://api.qrserver.com/v1/create-qr-code/?size=180x180&data=${encodeURIComponent(promoCode)}" alt="QR">`;
    }

    qrViewModal.classList.add('active');
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

  if (btnOpenMap) {
    btnOpenMap.addEventListener('click', () => {
      if (!currentMapLink) return;
      if (tg && tg.openLink) {
        tg.openLink(currentMapLink);
      } else {
        window.open(currentMapLink, '_blank');
      }
    });
  }

  if (btnCloseQrModal) {
    btnCloseQrModal.addEventListener('click', () => {
      qrViewModal.classList.remove('active');
    });
  }

  // ---------------------------------------------------------------- Referral

  if (btnCopyRef) {
    btnCopyRef.addEventListener('click', () => {
      const link = refLinkInput.value;
      const done = () => {
        btnCopyRef.innerText = '✅ Nusxalandi!';
        setTimeout(() => { btnCopyRef.innerText = '📋 Nusxalash'; }, 2000);
      };

      if (navigator.clipboard) {
        navigator.clipboard.writeText(link).then(done).catch(() => {
          refLinkInput.select();
          document.execCommand('copy');
          done();
        });
      } else {
        refLinkInput.select();
        document.execCommand('copy');
        done();
      }
    });
  }

  if (btnShareTg) {
    btnShareTg.addEventListener('click', () => {
      const link = refLinkInput.value;
      const shareText = encodeURIComponent(
        "🚀 Yoshlar Texnoparki CS2 Skin Roulette barabanida ishtirok eting va qimmatbaho yutuqlarni yutib oling!"
      );
      const shareUrl = `https://t.me/share/url?url=${encodeURIComponent(link)}&text=${shareText}`;

      if (tg && tg.openTelegramLink) {
        tg.openTelegramLink(shareUrl);
      } else {
        window.open(shareUrl, '_blank');
      }
    });
  }

  // ---------------------------------------------------------------- Start

  checkInitialUserStatus();
});
