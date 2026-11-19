const DAFTAR_LABEL = ['Normal', 'Spam', 'Phishing'];
const JALUR_ANIMASI_MASKOT = ''; // Isi setelah file Lottie pilihan disimpan lokal.
const preferensiGerakRingan = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

function mulaiTema() {
  let tema = localStorage.getItem('checkmail-tema') || 'gelap';
  terapkanTema(tema);
  document.querySelectorAll('[data-theme-toggle]').forEach((tombol) => {
    tombol.addEventListener('click', () => {
      tema = document.body.dataset.theme === 'gelap' ? 'terang' : 'gelap';
      localStorage.setItem('checkmail-tema', tema);
      terapkanTema(tema);
    });
  });
}

function terapkanTema(tema) {
  document.body.dataset.theme = tema;
  const metaTema = document.querySelector('meta[name="theme-color"]');
  if (metaTema) metaTema.content = tema === 'gelap' ? '#11130f' : '#f4f2e9';
  document.querySelectorAll('[data-theme-toggle]').forEach((tombol) => {
    const gelap = tema === 'gelap';
    tombol.setAttribute('aria-pressed', String(gelap));
    tombol.setAttribute('aria-label', gelap ? 'Aktifkan mode terang' : 'Aktifkan mode gelap');
    const ikon = tombol.querySelector('.theme-icon');
    const teks = tombol.querySelector('.theme-text');
    if (ikon) ikon.textContent = gelap ? '☾' : '☼';
    if (teks) teks.textContent = gelap ? 'Mode gelap' : 'Mode terang';
  });
}

function mulaiIlustrasiLottie() {
  const wadahSinyal = document.querySelector('#lottie-sinyal');
  if (!window.lottie || preferensiGerakRingan) return;
  if (wadahSinyal) {
    const animasiSinyal = window.lottie.loadAnimation({
      container: wadahSinyal, renderer: 'svg', loop: true, autoplay: true,
      path: '/assets/animations/guardian-pulse.json'
    });
    animasiSinyal.addEventListener('data_failed', () => { wadahSinyal.hidden = true; });
  }
  const wadahMaskot = document.querySelector('#lottie-maskot');
  if (wadahMaskot && JALUR_ANIMASI_MASKOT) {
    const animasiMaskot = window.lottie.loadAnimation({
      container: wadahMaskot, renderer: 'svg', loop: true, autoplay: true,
      path: JALUR_ANIMASI_MASKOT
    });
    animasiMaskot.addEventListener('DOMLoaded', () => {
      const ilustrasiFallback = document.querySelector('#ilustrasi-pengganti');
      if (ilustrasiFallback) ilustrasiFallback.hidden = true;
    });
  }
}

function amankanTautan(teks) {
  return teks
    .replace(/https:\/\//gi, 'hxxps://')
    .replace(/http:\/\//gi, 'hxxp://')
    .replace(/([a-z0-9-]+)\.(com|net|org|id|co|io|gov|edu|info|biz|xyz|app|site|online|me|ly|to|uk|us)(?=[/:?#\s]|$)/gi, '$1[.]$2')
    .replace(/\bwww\./gi, 'www[.]');
}

function buatElemen(tag, kelas, teks) {
  const elemen = document.createElement(tag);
  if (kelas) elemen.className = kelas;
  if (teks !== undefined) elemen.textContent = teks;
  return elemen;
}

async function panggilApi(url, opsi = {}) {
  const header = { ...(opsi.headers || {}) };
  if (!(opsi.body instanceof FormData)) header['Content-Type'] = 'application/json';
  const respons = await fetch(url, { ...opsi, headers: header });
  const data = await respons.json().catch(() => null);
  if (!respons.ok) {
    if (respons.status === 404) throw new Error('Endpoint fitur ini belum tersedia di server. Hentikan Flask dengan Ctrl+C lalu jalankan ulang backend/app.py.');
    if (respons.status === 405) throw new Error('Server menolak metode pemeriksaan. Restart Flask dengan backend/app.py dan pastikan halaman dibuka dari http://127.0.0.1:5000, bukan Go Live.');
    throw new Error(data?.kesalahan || `Server Check Mail menolak permintaan (HTTP ${respons.status}).`);
  }
  if (!data) throw new Error('Server merespons dengan format tidak dikenali. Restart Flask lalu coba lagi.');
  return data;
}

function formatTanggal(iso) {
  const tanggal = new Date(iso);
  return Number.isNaN(tanggal.getTime()) ? 'Baru saja' : new Intl.DateTimeFormat('id-ID', { dateStyle: 'medium', timeStyle: 'short' }).format(tanggal);
}

function renderSkor(probabilitas) {
  const wadah = document.querySelector('#daftar-skor');
  wadah.replaceChildren();
  DAFTAR_LABEL.forEach((label) => {
    const skor = Number(probabilitas[label] || 0);
    const baris = buatElemen('div', 'score-row');
    const judul = buatElemen('div', 'score-label');
    judul.append(buatElemen('span', '', label), buatElemen('span', '', `${(skor * 100).toFixed(1)}%`));
    const jalur = buatElemen('div', 'score-track');
    const isi = buatElemen('div', `score-fill ${label.toLowerCase()}`);
    isi.style.width = `${Math.max(0, Math.min(100, skor * 100))}%`;
    jalur.append(isi);
    baris.append(judul, jalur);
    wadah.append(baris);
  });
}

function renderIndikator(indikator) {
  const wadah = document.querySelector('#daftar-indikator');
  wadah.replaceChildren();
  document.querySelector('#jumlah-indikator').textContent = `${indikator.length} indikator`;
  if (!indikator.length) {
    wadah.append(buatElemen('p', 'no-indicator', 'Belum ada indikator umum yang ditemukan. Periksa alamat pengirim dan konteks pesan juga.'));
    return;
  }
  indikator.forEach((item) => {
    const chip = buatElemen('div', 'indicator-chip');
    chip.dataset.tingkat = item.tingkat;
    chip.append(buatElemen('strong', '', item.nama), buatElemen('span', '', item.penjelasan));
    wadah.append(chip);
  });
}

function tampilkanHasil(hasil, teksEmail) {
  const panel = document.querySelector('#panel-hasil');
  const kartu = document.querySelector('#kartu-vonis');
  kartu.dataset.label = hasil.label;
  document.querySelector('#ikon-vonis').textContent = hasil.label === 'Phishing' ? '!' : hasil.label === 'Spam' ? '↗' : '✓';
  document.querySelector('#label-hasil').textContent = hasil.label;
  const deskripsi = {
    Normal: 'Email ini masuk kategori Normal berdasarkan konteks yang terdeteksi. Pastikan alamat pengirim dan isi pesannya memang sesuai harapan.',
    Spam: 'Isi email mirip pesan promosi atau massal menurut model. Label ini bukan bukti bahwa pengirim palsu atau email adalah penipuan.',
    Phishing: 'Pesan menunjukkan sinyal risiko tinggi. Jangan bayar atau berikan data sebelum memverifikasi melalui kanal resmi.'
  };
  document.querySelector('#teks-vonis').textContent = deskripsi[hasil.label] || hasil.catatan;
  const catatanKlasifikasi = document.querySelector('#catatan-klasifikasi');
  const labelModel = hasil.label_model || hasil.label;
  const labelDiubahAturan = labelModel !== hasil.label;
  catatanKlasifikasi.hidden = !hasil.alasan_label || !labelDiubahAturan;
  catatanKlasifikasi.dataset.sumber = labelDiubahAturan ? 'aturan' : 'model';
  catatanKlasifikasi.textContent = labelModel !== hasil.label
    ? `Keputusan akhir: ${hasil.label}. Prediksi ML mentah: ${labelModel}. ${hasil.alasan_label}`
    : '';
  const rincianSkor = document.querySelector('#detail-skor-ml');
  rincianSkor.open = !labelDiubahAturan;
  document.querySelector('#catatan-skor').textContent = labelDiubahAturan
    ? `Keputusan akhir: ${hasil.label}. Aturan risiko mengubah prediksi ML mentah (${labelModel}) berdasarkan indikator yang ditemukan. Buka rincian skor ML jika ingin membandingkan keduanya.`
    : `Keputusan akhir mengikuti prediksi ML: ${hasil.label}. Skor tetap merupakan estimasi, bukan jaminan keamanan.`;
  const tindakan = {
    Normal: 'Jika pesan meminta data sensitif atau terasa tidak sesuai, verifikasi melalui kanal resmi.',
    Spam: 'Kalau pesan menyangkut pembayaran atau akun, buka aplikasi/situs resmi secara mandiri untuk memeriksa statusnya. Jangan jadikan label model ini satu-satunya dasar untuk menandai pengirim sebagai spam.',
    Phishing: 'Jangan klik, membalas, atau membagikan kode. Hubungi pengirim melalui alamat/nomor resmi yang kamu cari sendiri.'
  };
  document.querySelector('#teks-tindakan').textContent = tindakan[hasil.label] || 'Periksa pengirim dan konteks email.';
  renderSkor(hasil.probabilitas || {});
  renderIndikator(hasil.indikator || []);
  const tautan = hasil.tautan || [];
  const wadahTautan = document.querySelector('#tautan-wrap');
  const daftarTautan = document.querySelector('#daftar-tautan');
  daftarTautan.replaceChildren();
  wadahTautan.hidden = !tautan.length;
  tautan.forEach((item) => {
    const kartuTautan = buatElemen('article', 'link-card');
    kartuTautan.append(buatElemen('strong', '', item.domain || 'Domain tidak diketahui'));
    if (item.teks_tampil) kartuTautan.append(buatElemen('span', 'link-display-text', `Teks tombol: ${item.teks_tampil}`));
    const alamat = buatElemen('code', 'defanged-link', amankanTautan(item.url));
    kartuTautan.append(alamat);
    kartuTautan.append(buatElemen('small', '', item.indikator?.length ? item.indikator.join(' · ') : 'Tautan ditemukan di email. Redirect belum diperiksa.'));
    const tombolRedirect = buatElemen('button', 'redirect-button', 'Lacak redirect (hubungi situs)');
    tombolRedirect.type = 'button';
    kartuTautan.append(tombolRedirect);
    const petaRedirect = buatElemen('section', 'redirect-map-panel');
    petaRedirect.setAttribute('aria-label', 'Peta visual arah tautan');
    const kepalaPeta = buatElemen('div', 'redirect-map-heading');
    kepalaPeta.append(buatElemen('strong', '', 'PETA ARAH TAUTAN'));
    const statusPeta = buatElemen('span', 'redirect-map-status', 'Belum diperiksa');
    kepalaPeta.append(statusPeta);
    petaRedirect.append(kepalaPeta);
    const jalurPeta = buatElemen('div', 'redirect-flow');
    const nodeAwal = buatElemen('article', 'redirect-node redirect-node-source');
    nodeAwal.append(buatElemen('span', 'redirect-node-icon', '✉'));
    nodeAwal.append(buatElemen('small', '', 'TAUTAN DARI EMAIL'));
    nodeAwal.append(buatElemen('code', '', amankanTautan(item.url)));
    const statusNodeAwal = buatElemen('span', 'redirect-node-state', 'Menunggu pemeriksaan');
    nodeAwal.append(statusNodeAwal);
    jalurPeta.append(nodeAwal);
    const panahAwal = buatElemen('span', 'redirect-flow-arrow redirect-flow-pending', '⇢');
    panahAwal.setAttribute('aria-hidden', 'true');
    jalurPeta.append(panahAwal);
    const nodeTujuan = buatElemen('article', 'redirect-node redirect-node-pending');
    nodeTujuan.append(buatElemen('span', 'redirect-node-icon', '◎'));
    nodeTujuan.append(buatElemen('small', '', 'TUJUAN BERIKUTNYA'));
    nodeTujuan.append(buatElemen('code', '', 'Menunggu pemeriksaan'));
    nodeTujuan.append(buatElemen('span', 'redirect-node-state', 'Belum diketahui'));
    jalurPeta.append(nodeTujuan);
    petaRedirect.append(jalurPeta);
    const catatanPeta = buatElemen('small', 'redirect-map-note', 'Tujuan akhir belum dikonfirmasi.');
    petaRedirect.append(catatanPeta);
    kartuTautan.append(petaRedirect);
    tombolRedirect.addEventListener('click', async () => {
      tombolRedirect.disabled = true;
      tombolRedirect.textContent = 'Memeriksa header redirect…';
      statusPeta.textContent = 'Menghubungi situs…';
      statusPeta.className = 'redirect-map-status is-loading';
      statusNodeAwal.textContent = 'Permintaan dikirim';
      nodeTujuan.className = 'redirect-node redirect-node-pending';
      nodeTujuan.querySelector('code').textContent = 'Menunggu respons';
      nodeTujuan.querySelector('.redirect-node-state').textContent = 'Sedang memeriksa';
      catatanPeta.textContent = 'Menghubungi domain tautan; isi halaman tidak dibaca.';
      panahAwal.className = 'redirect-flow-arrow redirect-flow-loading';
      try {
        const data = await panggilApi('/api/check-redirect', { method: 'POST', body: JSON.stringify({ url: item.url }) });
        const rantai = data.hasil?.rantai || [];
        const statusAkhir = data.hasil?.status || '';
        const urlAkhir = data.hasil?.url_akhir || item.url;
        statusPeta.textContent = data.hasil?.terblokir ? 'Diblokir' : statusAkhir.includes('Batas waktu') ? 'Belum terkonfirmasi' : 'Pemeriksaan selesai';
        statusPeta.className = `redirect-map-status ${data.hasil?.terblokir ? 'is-blocked' : statusAkhir.includes('Batas waktu') ? 'is-unknown' : 'is-done'}`;
        jalurPeta.replaceChildren();
        const nodeSumber = buatElemen('article', 'redirect-node redirect-node-source');
        nodeSumber.append(buatElemen('span', 'redirect-node-icon', '✉'));
        nodeSumber.append(buatElemen('small', '', 'TAUTAN DARI EMAIL'));
        nodeSumber.append(buatElemen('code', '', amankanTautan(item.url)));
        const hopPertama = rantai[0];
        const statusSumber = hopPertama?.kode_http && hopPertama.url === item.url
          ? `${hopPertama.metode || 'HEAD'} · HTTP ${hopPertama.kode_http}${statusAkhir.includes('tidak ada redirect') ? ' · tujuan merespons' : ''}`
          : hopPertama?.kode_http ? `${hopPertama.metode || 'HEAD'} · HTTP ${hopPertama.kode_http}` : 'Tidak ada respons';
        nodeSumber.append(buatElemen('span', 'redirect-node-state', statusSumber));
        if (hopPertama?.kode_http && statusAkhir.includes('tidak ada redirect') && hopPertama.url === item.url) nodeSumber.classList.add('redirect-node-final');
        jalurPeta.append(nodeSumber);
        let urlTerakhirDiPeta = item.url;
        rantai.forEach((lompatan, nomor) => {
          if (lompatan.url === item.url && nomor === 0) return;
          const panah = buatElemen('span', 'redirect-flow-arrow', '→');
          panah.setAttribute('aria-hidden', 'true');
          jalurPeta.append(panah);
          const node = buatElemen('article', `redirect-node ${lompatan.kode_http ? 'redirect-node-hop' : 'redirect-node-blocked'}`);
          node.append(buatElemen('span', 'redirect-node-icon', lompatan.kode_http ? '↪' : '⛨'));
          const tujuanTerakhirMerespons = nomor === rantai.length - 1 && statusAkhir.includes('tidak ada redirect');
          node.append(buatElemen('small', '', lompatan.kode_http ? tujuanTerakhirMerespons ? 'TUJUAN AKHIR' : `LOMPATAN ${nomor + 1}` : 'TUJUAN DIBLOKIR'));
          node.append(buatElemen('code', '', amankanTautan(lompatan.url)));
          node.append(buatElemen('span', 'redirect-node-state', lompatan.kode_http ? `${lompatan.metode || 'HEAD'} · HTTP ${lompatan.kode_http}${tujuanTerakhirMerespons ? ' · merespons' : ''}` : 'Tidak dihubungi'));
          if (tujuanTerakhirMerespons) node.classList.add('redirect-node-final');
          jalurPeta.append(node);
          urlTerakhirDiPeta = lompatan.url;
        });
        const belumDikonfirmasi = statusAkhir.includes('Batas waktu') || statusAkhir.includes('Batas') || !rantai.length || data.hasil?.terblokir;
        if (urlAkhir && urlAkhir !== urlTerakhirDiPeta) {
          const panah = buatElemen('span', `redirect-flow-arrow ${belumDikonfirmasi ? 'redirect-flow-pending' : ''}`, '⇢');
          panah.setAttribute('aria-hidden', 'true');
          jalurPeta.append(panah);
          const nodeAkhir = buatElemen('article', `redirect-node ${data.hasil?.terblokir ? 'redirect-node-blocked' : belumDikonfirmasi ? 'redirect-node-pending' : 'redirect-node-final'}`);
          nodeAkhir.append(buatElemen('span', 'redirect-node-icon', data.hasil?.terblokir ? '⛨' : belumDikonfirmasi ? '…' : '◎'));
          nodeAkhir.append(buatElemen('small', '', data.hasil?.terblokir ? 'DIBLOKIR' : belumDikonfirmasi ? 'BELUM TERVERIFIKASI' : 'TUJUAN AKHIR'));
          nodeAkhir.append(buatElemen('code', '', amankanTautan(urlAkhir)));
          nodeAkhir.append(buatElemen('span', 'redirect-node-state', data.hasil?.terblokir ? 'Tidak dihubungi' : belumDikonfirmasi ? 'Belum ada respons' : 'Terkonfirmasi merespons'));
          jalurPeta.append(nodeAkhir);
        }
        if (!rantai.length && urlAkhir === item.url) {
          nodeSumber.classList.add('redirect-node-unknown');
          nodeSumber.querySelector('.redirect-node-state').textContent = 'Belum ada server yang merespons';
          const panahPenantian = buatElemen('span', 'redirect-flow-arrow redirect-flow-pending', '⇢');
          panahPenantian.setAttribute('aria-hidden', 'true');
          jalurPeta.append(panahPenantian);
          const tujuanTertunda = buatElemen('article', 'redirect-node redirect-node-pending');
          tujuanTertunda.append(buatElemen('span', 'redirect-node-icon', '…'));
          tujuanTertunda.append(buatElemen('small', '', 'TUJUAN BERIKUTNYA'));
          tujuanTertunda.append(buatElemen('code', '', 'Belum diketahui'));
          tujuanTertunda.append(buatElemen('span', 'redirect-node-state', statusAkhir || 'Tidak ada respons'));
          jalurPeta.append(tujuanTertunda);
        }
        catatanPeta.textContent = `${statusAkhir || 'Status tidak diketahui'} · ${data.catatan || 'Peta ini menunjukkan respons jaringan, bukan reputasi atau keamanan situs.'}`;
      } catch (kesalahan) {
        statusPeta.textContent = 'Pemeriksaan gagal';
        statusPeta.className = 'redirect-map-status is-unknown';
        statusNodeAwal.textContent = 'Alamat awal saja yang diketahui';
        nodeTujuan.querySelector('code').textContent = 'Tujuan belum diketahui';
        nodeTujuan.querySelector('.redirect-node-state').textContent = kesalahan.message;
        catatanPeta.textContent = 'Tidak ada tujuan redirect yang berhasil dikonfirmasi.';
      } finally {
        tombolRedirect.disabled = false;
        tombolRedirect.textContent = 'Periksa lagi';
      }
    });
    daftarTautan.append(kartuTautan);
  });
  document.querySelector('#pratinjau-email').textContent = amankanTautan(teksEmail);
  panel.hidden = false;
  panel.scrollIntoView({ behavior: preferensiGerakRingan ? 'auto' : 'smooth', block: 'start' });
}

async function perbaruiStatistik(prefix = 'stat-') {
  try {
    const data = await panggilApi('/api/stats');
    const total = document.querySelector(`#${prefix}total`);
    if (total) total.textContent = data.total;
    DAFTAR_LABEL.forEach((label) => {
      const jumlah = data.per_label[label] || 0;
      const angka = document.querySelector(`#${prefix}${label.toLowerCase()}`);
      if (angka) angka.textContent = jumlah;
      const batang = document.querySelector(`#bar-${label.toLowerCase()}`);
      if (batang) batang.style.width = `${data.total ? Math.max(3, jumlah / data.total * 100) : 0}%`;
    });
    return data;
  } catch {
    const total = document.querySelector(`#${prefix}total`);
    if (total) total.textContent = '—';
    return null;
  }
}

function tampilkanStatus(teks, jenis = '') {
  const status = document.querySelector('#status');
  if (!status) return;
  status.textContent = teks;
  status.dataset.jenis = jenis;
}

function mulaiPemindai() {
  const areaTeks = document.querySelector('#teks-email');
  if (!areaTeks) return;
  const tombolAnalisis = document.querySelector('#tombol-analisis');
  const tombolBersihkan = document.querySelector('#tombol-bersihkan');
  const indikatorMuat = document.querySelector('#scan-progress');
  const inputBerkas = document.querySelector('#berkas-email');
  const areaLepasBerkas = document.querySelector('#area-lepas-berkas');
  const labelTombol = tombolAnalisis.querySelector('.scan-button-label');
  const contohPhishing = 'Subjek: Akun Anda akan ditangguhkan\n\nKami mendeteksi aktivitas tidak biasa pada akun Anda. Verifikasi akun hari ini agar akses tidak dinonaktifkan. Balas dengan kata sandi dan kode OTP Anda.';
  if (new URLSearchParams(window.location.search).get('contoh') === 'phishing') {
    areaTeks.value = contohPhishing;
    areaTeks.dispatchEvent(new Event('input'));
    tampilkanStatus('Contoh sintetis dimuat. Klik Periksa email untuk mencoba.');
    areaTeks.focus();
  }

  areaTeks.addEventListener('input', () => {
    document.querySelector('#penghitung').textContent = `${areaTeks.value.length.toLocaleString('id-ID')} / 20.000`;
  });
  async function prosesBerkasEmail(berkas) {
    if (!berkas) return;
    const statusBerkas = document.querySelector('#status-berkas');
    if (!/\.(eml|txt|pdf)$/i.test(berkas.name)) { statusBerkas.textContent = 'Format berkas tidak didukung.'; tampilkanStatus('Pilih berkas .eml, .txt, atau .pdf.', 'galat'); inputBerkas.value = ''; return; }
    if (berkas.size > 10 * 1_048_576) { statusBerkas.textContent = 'Berkas melebihi batas 10 MB.'; tampilkanStatus('Pilih berkas yang lebih kecil dari 10 MB.', 'galat'); inputBerkas.value = ''; return; }
    const dataForm = new FormData();
    dataForm.append('berkas_email', berkas);
    tombolAnalisis.disabled = true;
    tombolAnalisis.classList.add('sedang-muat');
    labelTombol.textContent = 'Memeriksa berkas…';
    indikatorMuat.hidden = false;
    indikatorMuat.querySelector('strong').textContent = 'Membaca berkas email…';
    indikatorMuat.querySelector('small').textContent = 'Mengurai header, isi, dan tautan secara lokal; tautan tidak dibuka.';
    tampilkanStatus('');
    try {
      const data = await panggilApi('/api/analyze-file', { method: 'POST', body: dataForm });
      areaTeks.value = data.teks_diperiksa || '';
      areaTeks.dispatchEvent(new Event('input'));
      if (data.metadata) {
        document.querySelector('#alamat-pengirim').value = data.metadata.alamat_pengirim || '';
        document.querySelector('#alamat-balasan').value = data.metadata.alamat_balasan || '';
      }
      tampilkanHasil(data.hasil, data.teks_diperiksa || '');
      statusBerkas.textContent = `${berkas.name} berhasil dianalisis${data.metadata?.subjek ? ` · Subjek: ${data.metadata.subjek}` : ''}`;
      tampilkanStatus('Pemeriksaan lokal selesai. Tujuan redirect dapat diperiksa satu per satu; hasil bukan kepastian.', 'sukses');
      await perbaruiStatistik();
    } catch (kesalahan) {
      statusBerkas.textContent = 'Berkas belum berhasil diperiksa.';
      tampilkanStatus(kesalahan.message, 'galat');
    } finally {
      tombolAnalisis.disabled = false;
      tombolAnalisis.classList.remove('sedang-muat');
      labelTombol.textContent = 'Periksa email';
      indikatorMuat.hidden = true;
      inputBerkas.value = '';
    }
  }
  inputBerkas.addEventListener('change', () => prosesBerkasEmail(inputBerkas.files?.[0]));
  ['dragenter', 'dragover'].forEach((jenis) => areaLepasBerkas.addEventListener(jenis, (peristiwa) => {
    peristiwa.preventDefault(); peristiwa.stopPropagation(); areaLepasBerkas.classList.add('sedang-dijatuhkan');
  }));
  ['dragleave', 'dragend'].forEach((jenis) => areaLepasBerkas.addEventListener(jenis, (peristiwa) => {
    peristiwa.preventDefault(); areaLepasBerkas.classList.remove('sedang-dijatuhkan');
  }));
  areaLepasBerkas.addEventListener('drop', (peristiwa) => {
    peristiwa.preventDefault(); peristiwa.stopPropagation(); areaLepasBerkas.classList.remove('sedang-dijatuhkan');
    const daftarBerkas = Array.from(peristiwa.dataTransfer?.files || []);
    if (daftarBerkas.length !== 1) { tampilkanStatus('Lepaskan satu berkas email saja.', 'galat'); return; }
    prosesBerkasEmail(daftarBerkas[0]);
  });
  areaTeks.addEventListener('paste', (peristiwa) => {
    const tempel = (peristiwa.clipboardData || window.clipboardData).getData('text');
    if (tempel.length <= 20_000) return;
    peristiwa.preventDefault();
    const awal = areaTeks.selectionStart;
    const akhir = areaTeks.selectionEnd;
    const tersedia = 20_000 - (areaTeks.value.length - (akhir - awal));
    areaTeks.setRangeText(tempel.slice(0, Math.max(0, tersedia)), awal, akhir, 'end');
    areaTeks.dispatchEvent(new Event('input'));
    tampilkanStatus('Teks dipotong pada batas 20.000 karakter.', 'info');
  });

  tombolAnalisis.addEventListener('click', async () => {
    const teksEmail = areaTeks.value.trim();
    if (!teksEmail) { tampilkanStatus('Tempel isi email dulu sebelum diperiksa.', 'galat'); areaTeks.focus(); return; }
    tombolAnalisis.disabled = true;
    tombolAnalisis.classList.add('sedang-muat');
    labelTombol.textContent = 'Sedang memeriksa…';
    indikatorMuat.hidden = false;
    tampilkanStatus('');
    try {
      const data = await panggilApi('/api/analyze', { method: 'POST', body: JSON.stringify({ teks_email: teksEmail, alamat_pengirim: document.querySelector('#alamat-pengirim').value.trim(), alamat_balasan: document.querySelector('#alamat-balasan').value.trim() }) });
      tampilkanHasil(data.hasil, teksEmail);
      tampilkanStatus('Pemeriksaan selesai. Gunakan hasil sebagai panduan, bukan kepastian.', 'sukses');
      await perbaruiStatistik();
    } catch (kesalahan) {
      tampilkanStatus(kesalahan.message, 'galat');
    } finally {
      tombolAnalisis.disabled = false;
      tombolAnalisis.classList.remove('sedang-muat');
      labelTombol.textContent = 'Periksa email';
      indikatorMuat.hidden = true;
    }
  });

  tombolBersihkan.addEventListener('click', () => {
    areaTeks.value = '';
    areaTeks.dispatchEvent(new Event('input'));
    areaTeks.focus();
    tampilkanStatus('Kolom input dibersihkan.', 'info');
  });
  perbaruiStatistik();
}

let semuaRiwayat = [];
let filterRiwayat = 'semua';
let jumlahTotalRiwayat = 0;

function renderRiwayat() {
  const badanTabel = document.querySelector('#riwayat-body');
  const status = document.querySelector('#status-riwayat');
  if (!badanTabel || !status) return;
  badanTabel.replaceChildren();
  const dataTampil = filterRiwayat === 'semua' ? semuaRiwayat : semuaRiwayat.filter((item) => item.label === filterRiwayat);
  if (!dataTampil.length) {
    const barisKosong = buatElemen('tr', 'empty-row');
    const sel = buatElemen('td', '', semuaRiwayat.length ? 'Tidak ada hasil untuk kategori ini.' : 'Belum ada email yang diperiksa. Mulai dari halaman Scan.');
    sel.colSpan = 4;
    barisKosong.append(sel);
    badanTabel.append(barisKosong);
  } else {
    dataTampil.forEach((item) => {
      const baris = buatElemen('tr', '');
      const skor = Math.max(...Object.values(item.probabilitas || {}).map(Number), 0);
      const selWaktu = buatElemen('td', 'history-date', formatTanggal(item.dibuat_pada));
      const selLabel = buatElemen('td', '');
      const label = buatElemen('span', 'history-label', item.label);
      label.dataset.label = item.label;
      selLabel.append(label);
      const selTeks = buatElemen('td', 'history-snippet', amankanTautan(item.cuplikan_teks || 'Email dianalisis'));
      const selSkor = buatElemen('td', 'history-score', `${(skor * 100).toFixed(0)}%`);
      baris.append(selWaktu, selLabel, selTeks, selSkor);
      badanTabel.append(baris);
    });
  }
  status.textContent = jumlahTotalRiwayat > 100
    ? `Menampilkan 100 pemeriksaan terbaru dari ${jumlahTotalRiwayat}. Ekspor mencakup riwayat yang sedang dimuat.`
    : `${dataTampil.length} pemeriksaan ditampilkan.`;
}

async function mulaiHalamanRiwayat() {
  const status = document.querySelector('#status-riwayat');
  if (!status) return;
  try {
    const [data, statistik] = await Promise.all([panggilApi('/api/history?limit=100'), perbaruiStatistik('stat-history-')]);
    semuaRiwayat = data.riwayat || [];
    jumlahTotalRiwayat = statistik ? statistik.total : semuaRiwayat.length;
    if (statistik) {
      DAFTAR_LABEL.forEach((label) => {
        const angka = document.querySelector(`#stat-history-${label.toLowerCase()}`);
        if (angka) angka.textContent = statistik.per_label[label] || 0;
      });
    }
    renderRiwayat();
  } catch (kesalahan) {
    status.textContent = `Riwayat tidak dapat dimuat: ${kesalahan.message}`;
    status.dataset.jenis = 'galat';
  }

  document.querySelectorAll('[data-filter]').forEach((tombol) => {
    tombol.addEventListener('click', () => {
      filterRiwayat = tombol.dataset.filter;
      document.querySelectorAll('[data-filter]').forEach((item) => {
        const aktif = item === tombol;
        item.classList.toggle('aktif', aktif);
        item.setAttribute('aria-pressed', String(aktif));
      });
      renderRiwayat();
    });
  });

  document.querySelector('#tombol-ekspor').addEventListener('click', () => {
    const dataEkspor = filterRiwayat === 'semua' ? semuaRiwayat : semuaRiwayat.filter((item) => item.label === filterRiwayat);
    const baris = [['Waktu', 'Kategori', 'Cuplikan', 'Skor tertinggi', 'Jumlah indikator']];
    dataEkspor.forEach((item) => {
      const skor = Math.max(...Object.values(item.probabilitas || {}).map(Number), 0);
      baris.push([formatTanggal(item.dibuat_pada), item.label, amankanTautan(item.cuplikan_teks || ''), `${(skor * 100).toFixed(1)}%`, String((item.indikator || []).length)]);
    });
    const csv = '\uFEFF' + baris.map((kolom) => kolom.map((nilai) => `"${String(nilai).replace(/"/g, '""')}"`).join(',')).join('\r\n');
    const tautan = document.createElement('a');
    tautan.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    tautan.download = 'check-mail-riwayat.csv';
    tautan.click();
    window.setTimeout(() => URL.revokeObjectURL(tautan.href), 1000);
  });

  document.querySelector('#tombol-hapus-riwayat').addEventListener('click', async () => {
    if (!window.confirm('Hapus semua riwayat pemeriksaan di perangkat ini?')) return;
    try {
      await panggilApi('/api/history', { method: 'DELETE' });
      semuaRiwayat = [];
      jumlahTotalRiwayat = 0;
      await perbaruiStatistik('stat-history-');
      DAFTAR_LABEL.forEach((label) => { document.querySelector(`#stat-history-${label.toLowerCase()}`).textContent = '0'; });
      renderRiwayat();
    } catch (kesalahan) {
      status.textContent = `Riwayat gagal dihapus: ${kesalahan.message}`;
      status.dataset.jenis = 'galat';
    }
  });
}

mulaiTema();
mulaiIlustrasiLottie();
mulaiPemindai();
if (document.body.dataset.halaman === 'riwayat') mulaiHalamanRiwayat();


