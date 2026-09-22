/**
 * Gift Box Roulette Scroll Engine with Web Audio API Sound Generator
 */

class RouletteEngine {
  constructor(trackElementId, viewportElementId) {
    this.track = document.getElementById(trackElementId);
    this.viewport = document.getElementById(viewportElementId);
    this.isSpinning = false;
    this.soundEnabled = true;
    this.audioCtx = null;
    this.cardWidth = 130; // px
    this.cardGap = 12;    // px
    this.itemTotalWidth = this.cardWidth + this.cardGap; // 142px
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
    const defaultIcon = prize.rarity === 'LEGENDARY' ? '🏆' :
                        prize.rarity === 'EPIC' ? '💎' :
                        prize.rarity === 'RARE' ? '🎁' : '⭐';

    // display_image — dashboarddan yuklangan fayl yoki tashqi URL.
    // Nisbiy yo'llar (/media/..., /static/...) ham qo'llab-quvvatlanadi.
    const imageSrc = prize.display_image || prize.image_url || '';

    // Emoji doim chiziladi; rasm uning ustiga tushadi va yuklanmasa o'zini
    // o'chiradi — shunda ostidagi emoji ko'rinib qoladi.
    const imageContent = `
        <div class="card-icon card-icon-wrap">
          <span class="card-icon-fallback">${defaultIcon}</span>
          ${imageSrc ? `<img src="${imageSrc}" alt="" onerror="this.remove()">` : ''}
        </div>`;

    return `
      <div class="skin-card rarity-${prize.rarity}" data-index="${index}" data-prize-id="${prize.id}">
        <div class="rarity-badge">${prize.rarity}</div>
        ${imageContent}
        <div class="card-title">${prize.title}</div>
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

  spin(allPrizes, winningPrize, targetIndex = 65, onCompleteCallback) {
    if (this.isSpinning) return;
    this.initAudio();
    this.isSpinning = true;

    // Build 80 cards
    this.populateTrack(allPrizes, winningPrize, targetIndex, 80);

    const viewportWidth = this.viewport.offsetWidth;
    const cardCenter = (targetIndex * this.itemTotalWidth) + 10 + (this.cardWidth / 2);
    
    // Add minor random offset (-30px to +30px) for organic feel
    const randomJitter = (Math.random() * 60) - 30;
    const targetTranslateX = -(cardCenter - (viewportWidth / 2) + randomJitter);

    // Audio ticking animation simulation
    let lastTickCardIndex = -1;
    const startTime = Date.now();
    const durationMs = 5000;

    const tickInterval = setInterval(() => {
      const elapsed = Date.now() - startTime;
      if (elapsed >= durationMs) {
        clearInterval(tickInterval);
        return;
      }

      // Calculate current position based on cubic-bezier progression (approx)
      const progress = elapsed / durationMs;
      // Cubic bezier (0.12, 0.8, 0.2, 1) approximation
      const easeProgress = 1 - Math.pow(1 - progress, 3);
      const currentX = Math.abs(targetTranslateX * easeProgress);
      const currentCardIndex = Math.floor(currentX / this.itemTotalWidth);

      if (currentCardIndex !== lastTickCardIndex) {
        lastTickCardIndex = currentCardIndex;
        this.playTickSound();
      }
    }, 40);

    // Force reflow
    void this.track.offsetWidth;

    // Apply CSS transition
    this.track.style.transition = 'transform 5s cubic-bezier(0.12, 0.8, 0.2, 1)';
    this.track.style.transform = `translateX(${targetTranslateX}px)`;

    setTimeout(() => {
      this.isSpinning = false;
      this.playWinSound();

      // Highlight winning card
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
