/**
 * Gift Box Roulette Scroll Engine with Web Audio API Sound Generator
 */

// Nodirlik darajalari — barcha joyda bir xil nom va ikonka
const RARITY = {
  COMMON:    { label: 'Oddiy',     icon: '⭐' },
  RARE:      { label: 'Noyob',     icon: '🎁' },
  EPIC:      { label: 'Epik',      icon: '💎' },
  LEGENDARY: { label: 'Afsonaviy', icon: '🏆' },
};

function rarityInfo(rarity) {
  return RARITY[rarity] || RARITY.COMMON;
}

/** innerHTML ga tushadigan har qanday matn shu yerdan o'tadi */
function escapeHTML(value) {
  return String(value == null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

const prefersReducedMotion = () =>
  window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

class RouletteEngine {
  constructor(trackElementId, viewportElementId) {
    this.track = document.getElementById(trackElementId);
    this.viewport = document.getElementById(viewportElementId);
    this.isSpinning = false;
    this.soundEnabled = true;
    this.audioCtx = null;
    this.cardWidth = 130; // px — style.css dagi .prize-card bilan bir xil
    this.cardGap = 12;    // px
    this.itemTotalWidth = this.cardWidth + this.cardGap; // 142px

    // Har bir karta o'tganda yengil titrash (Telegram ichida)
    const tg = window.Telegram?.WebApp;
    this.haptic = tg && tg.initData && tg.isVersionAtLeast?.('6.1') ? tg.HapticFeedback : null;
  }

  initAudio() {
    if (!this.audioCtx) {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (AudioCtx) {
        this.audioCtx = new AudioCtx();
      }
    }
    if (this.audioCtx && this.audioCtx.state === 'suspended') {
      this.audioCtx.resume();
    }
  }

  playTickSound() {
    if (!this.soundEnabled || !this.audioCtx) return;
    try {
      const osc = this.audioCtx.createOscillator();
      const gain = this.audioCtx.createGain();
      osc.type = 'triangle';
      osc.frequency.setValueAtTime(440, this.audioCtx.currentTime);
      osc.frequency.exponentialRampToValueAtTime(120, this.audioCtx.currentTime + 0.04);

      gain.gain.setValueAtTime(0.15, this.audioCtx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, this.audioCtx.currentTime + 0.04);

      osc.connect(gain);
      gain.connect(this.audioCtx.destination);
      osc.start();
      osc.stop(this.audioCtx.currentTime + 0.04);
    } catch (e) {
      console.warn("Audio tick error:", e);
    }
  }

  playWinSound() {
    if (!this.soundEnabled || !this.audioCtx) return;
    try {
      const notes = [523.25, 659.25, 783.99, 1046.50]; // C5, E5, G5, C6
      notes.forEach((freq, idx) => {
        const osc = this.audioCtx.createOscillator();
        const gain = this.audioCtx.createGain();
        const startTime = this.audioCtx.currentTime + (idx * 0.08);

        osc.type = 'sine';
        osc.frequency.setValueAtTime(freq, startTime);

        gain.gain.setValueAtTime(0.2, startTime);
        gain.gain.exponentialRampToValueAtTime(0.001, startTime + 0.4);

        osc.connect(gain);
        gain.connect(this.audioCtx.destination);
        osc.start(startTime);
        osc.stop(startTime + 0.4);
      });
    } catch (e) {
      console.warn("Audio win error:", e);
    }
  }

  createCardHTML(prize, index) {
    const info = rarityInfo(prize.rarity);

    // display_image — dashboarddan yuklangan fayl yoki tashqi URL.
    // Nisbiy yo'llar (/media/..., /static/...) ham qo'llab-quvvatlanadi.
    const imageSrc = prize.display_image || prize.image_url || '';

    // Emoji doim chiziladi; rasm uning ustiga tushadi va yuklanmasa o'zini
    // o'chiradi — shunda ostidagi emoji ko'rinib qoladi.
    return `
      <div class="prize-card rarity-${escapeHTML(prize.rarity)}" data-index="${index}" data-prize-id="${escapeHTML(prize.id)}">
        <div class="rarity-badge">${info.label}</div>
        <div class="card-icon">
          <span class="card-icon-fallback">${info.icon}</span>
          ${imageSrc ? `<img src="${escapeHTML(imageSrc)}" alt="" loading="lazy" onerror="this.remove()">` : ''}
        </div>
        <div class="card-title">${escapeHTML(prize.title)}</div>
      </div>
    `;
  }

  populateTrack(allPrizes, winningPrize = null, targetIndex = 65, totalCards = 80) {
    this.track.style.transition = 'none';
    this.track.style.transform = 'translateX(0px)';
    this.track.innerHTML = '';

    const cardsHTML = [];
    for (let i = 0; i < totalCards; i++) {
      let prize;
      if (winningPrize && i === targetIndex) {
        prize = winningPrize;
      } else {
        prize = allPrizes[Math.floor(Math.random() * allPrizes.length)];
      }
      cardsHTML.push(this.createCardHTML(prize, i));
    }

    this.track.innerHTML = cardsHTML.join('');
  }

  /**
   * @param durationMs  birinchi aylantirish uzunroq, keyingilari qisqaroq
   *                    (app.js hal qiladi). Harakatni kamaytirish yoqilgan
   *                    bo'lsa animatsiya deyarli bo'lmaydi.
   */
  spin(allPrizes, winningPrize, targetIndex = 65, onCompleteCallback, durationMs = 5000) {
    if (this.isSpinning) return;
    this.initAudio();
    this.isSpinning = true;

    if (prefersReducedMotion()) durationMs = 900;

    // Build 80 cards
    this.populateTrack(allPrizes, winningPrize, targetIndex, 80);

    const viewportWidth = this.viewport.offsetWidth;
    const cardCenter = (targetIndex * this.itemTotalWidth) + 10 + (this.cardWidth / 2);

    // Add minor random offset (-30px to +30px) for organic feel
    const randomJitter = (Math.random() * 60) - 30;
    const targetTranslateX = -(cardCenter - (viewportWidth / 2) + randomJitter);

    // Ovoz va titrash — kartalar ko'rsatkichdan o'tgan sari
    let lastTickCardIndex = -1;
    const startTime = Date.now();

    const tickInterval = setInterval(() => {
      const elapsed = Date.now() - startTime;
      if (elapsed >= durationMs) {
        clearInterval(tickInterval);
        return;
      }

      // Cubic bezier (0.12, 0.8, 0.2, 1) approximation
      const progress = elapsed / durationMs;
      const easeProgress = 1 - Math.pow(1 - progress, 3);
      const currentX = Math.abs(targetTranslateX * easeProgress);
      const currentCardIndex = Math.floor(currentX / this.itemTotalWidth);

      if (currentCardIndex !== lastTickCardIndex) {
        lastTickCardIndex = currentCardIndex;
        this.playTickSound();
        if (this.haptic) this.haptic.selectionChanged();
      }
    }, 40);

    // Force reflow
    void this.track.offsetWidth;

    this.track.style.transition = `transform ${durationMs}ms cubic-bezier(0.12, 0.8, 0.2, 1)`;
    this.track.style.transform = `translateX(${targetTranslateX}px)`;

    setTimeout(() => {
      this.isSpinning = false;
      this.playWinSound();

      const targetCard = this.track.querySelector(`[data-index="${targetIndex}"]`);
      if (targetCard) {
        targetCard.classList.add('winning-highlight');
      }

      if (typeof onCompleteCallback === 'function') {
        onCompleteCallback(winningPrize);
      }
    }, durationMs + 200);
  }
}
