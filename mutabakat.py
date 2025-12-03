import streamlit as st
import pandas as pd
import re
import io
import time
import warnings
import json
import os
from datetime import timedelta

# Uyarıları gizle
warnings.filterwarnings("ignore")

# --- 1. AYARLAR VE GÜVENLİK ---
st.set_page_config(page_title="Mutabakat Pro V62 (Sade)", layout="wide")

if 'analiz_yapildi' not in st.session_state:
    st.session_state['analiz_yapildi'] = False
if 'sonuclar' not in st.session_state:
    st.session_state['sonuclar'] = {}

# Hafıza Dosyası
CONFIG_FILE = "ayarlar.json"

def ayarlari_yukle():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: return {}
    return {}

def ayarlari_kaydet(yeni_ayarlar):
    mevcut = ayarlari_yukle()
    mevcut.update(yeni_ayarlar)
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(mevcut, f, ensure_ascii=False, indent=4)
    except: pass

if 'column_prefs' not in st.session_state:
    st.session_state['column_prefs'] = ayarlari_yukle()

hide_st_style = """
            <style>
            #MainMenu {visibility: hidden;}
            header {visibility: hidden;}
            footer {visibility: hidden;}
            .stAppDeployButton {display:none;}
            [data-testid="stToolbar"] {visibility: hidden !important;}
            .block-container {padding-top: 1rem;}
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

# --- 2. YARDIMCI FONKSİYONLAR ---

def get_smart_index(options, target_name, filename, key_suffix):
    # Hafızadan veya Tahminden index bulur
    if filename in st.session_state['column_prefs']:
        saved_col = st.session_state['column_prefs'][filename].get(key_suffix)
        if saved_col in options: return options.index(saved_col)
    for i, opt in enumerate(options):
        if str(opt).strip().lower() == target_name.lower(): return i
    return 0

@st.cache_data
def belge_no_temizle(val):
    """Sadece rakamları bırakır."""
    if isinstance(val, (pd.Series, list, tuple)): val = val.iloc[0] if hasattr(val, 'iloc') else val[0]
    if pd.isna(val): return ""
    s = str(val)
    res = ''.join(filter(str.isdigit, s))
    if res: return str(int(res)) 
    return ""

@st.cache_data
def referans_no_temizle(val):
    """Özel karakterleri atar, baştaki sıfırları siler."""
    if isinstance(val, (pd.Series, list, tuple)): val = val.iloc[0] if hasattr(val, 'iloc') else val[0]
    if pd.isna(val): return ""
    if isinstance(val, float): val = f"{val:.0f}"
    s = str(val).strip().upper()
    s = re.sub(r'[^A-Z0-9]', '', s)
    s = s.lstrip('0')
    return s

def safe_strftime(val):
    if isinstance(val, (pd.Series, list, tuple)): val = val.iloc[0] if hasattr(val, 'iloc') else val[0]
    if pd.isna(val): return ""
    try: return val.strftime('%d.%m.%Y')
    except: return ""

def excel_indir(dfs_dict):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # 1. ÖZET Sayfası
        if "ÖZET" in dfs_dict:
            dfs_dict["ÖZET"].to_excel(writer, index=False, sheet_name="OZET")
        
        # 2. DETAYLAR Sayfası (Tüm veriler tek listede)
        master_df = pd.DataFrame()
        for key, df in dfs_dict.items():
            if key != "ÖZET" and not df.empty:
                df_copy = df.copy()
                df_copy.insert(0, "Kategori", key)
                master_df = pd.concat([master_df, df_copy], ignore_index=True)
        
        if not master_df.empty:
            master_df.to_excel(writer, index=False, sheet_name="DETAYLAR")
            
            # Formatlama
            worksheet = writer.sheets["DETAYLAR"]
            for column_cells in worksheet.columns:
                try:
                    length = max(len(str(cell.value) if cell.value else "") for cell in column_cells)
                    worksheet.column_dimensions[column_cells[0].column_letter].width = min(length + 2, 50)
                except: pass

    return output.getvalue()

def ozet_tablo_olustur(df_biz, df_onlar):
    # Ham veri üzerinden özet
    biz = df_biz.copy()
    biz['Net'] = biz['Borc'] - biz['Alacak']
    grp_biz = biz.groupby('Para_Birimi')['Net'].sum().reset_index().rename(columns={'Net': 'Biz_Bakiye'})
    
    onlar = df_onlar.copy()
    onlar['Net'] = onlar['Borc'] - onlar['Alacak']
    grp_onlar = onlar.groupby('Para_Birimi')['Net'].sum().reset_index().rename(columns={'Net': 'Onlar_Bakiye'})
    
    ozet = pd.merge(grp_biz, grp_onlar, on='Para_Birimi', how='outer').fillna(0)
    # Yönlü toplam farkı verir (Biri +, biri - ise)
    ozet['Fark'] = ozet['Biz_Bakiye'] + ozet['Onlar_Bakiye']
    return ozet

def veri_hazirla(df, config, taraf_adi, extra_cols=[]):
    df = df.loc[:, ~df.columns.duplicated()]
    df_copy = df.copy()
    
    df_new = pd.DataFrame()
    for col in extra_cols:
        if col in df_copy.columns: df_new[col] = df_copy[col].astype(str)

    # Tarih
    df_new['Tarih'] = pd.to_datetime(df_copy[config['tarih_col']], dayfirst=True, errors='coerce')
    
    # Ödeme Tarihi (Varsa)
    if config.get('tarih_odeme_col') and config['tarih_odeme_col'] != "Seçiniz...":
        df_new['Tarih_Odeme'] = pd.to_datetime(df_copy[config['tarih_odeme_col']], dayfirst=True, errors='coerce')
    else:
        df_new['Tarih_Odeme'] = df_new['Tarih']

    # Belge No & Match ID
    df_new['Orijinal_Belge_No'] = df_copy[config['belge_col']].astype(str)
    df_new['Match_ID'] = df_new['Orijinal_Belge_No'].apply(lambda x: ''.join(filter(str.isdigit, str(x))))
    df_new['Match_ID'] = df_new['Match_ID'].replace(r'^0+', '', regex=True) # Baştaki sıfırları sil
    
    # Referans No
    if config.get('odeme_ref_col') and config['odeme_ref_col'] != "Seçiniz...":
        df_new['Payment_ID'] = df_copy[config['odeme_ref_col']].apply(referans_no_temizle)
    else:
        df_new['Payment_ID'] = ""

    df_new['Kaynak'] = taraf_adi
    
    # Döviz
    doviz_aktif = False
    if config.get('doviz_cinsi_col') and config['doviz_cinsi_col'] != "Seçiniz...":
        df_new['Para_Birimi'] = df_copy[config['doviz_cinsi_col']].astype(str).str.upper().str.strip()
        df_new['Para_Birimi'] = df_new['Para_Birimi'].replace({'TL': 'TRY', 'TRL': 'TRY'})
        doviz_aktif = True
    else:
        df_new['Para_Birimi'] = "TRY"
        
    if config.get('doviz_tutar_col') and config['doviz_tutar_col'] != "Seçiniz...":
        df_new['Doviz_Tutari'] = pd.to_numeric(df_copy[config['doviz_tutar_col']], errors='coerce').fillna(0).abs()
        doviz_aktif = True
    else:
        df_new['Doviz_Tutari'] = 0.0

    # Tutar (Tek veya Ayrı)
    if "Tek Kolon" in config['tutar_tipi']:
        col_name = config['tutar_col']
        ham = pd.to_numeric(df_copy[col_name], errors='coerce').fillna(0)
        rol = config.get('rol_kodu', 'Biz Alıcıyız') 
        if rol == "Biz Alıcıyız":
            df_new['Borc'] = ham.where(ham > 0, 0)
            df_new['Alacak'] = ham.where(ham < 0, 0).abs()
        else:
            df_new['Alacak'] = ham.where(ham > 0, 0)
            df_new['Borc'] = ham.where(ham < 0, 0).abs()
    else:
        df_new['Borc'] = pd.to_numeric(df_copy[config['borc_col']], errors='coerce').fillna(0)
        df_new['Alacak'] = pd.to_numeric(df_copy[config['alacak_col']], errors='coerce').fillna(0)

    return df_new, doviz_aktif

def grupla_ve_ayir(df, is_doviz_aktif):
    """
    1. Match_ID'si olanları GRUPLA (Netleştir).
    2. Match_ID'si olmayanları (Ödeme vb.) AYIR.
    """
    if df.empty: return pd.DataFrame(), pd.DataFrame()
    
    # Ayrıştır
    mask_ids = (df['Match_ID'] != "") & (df['Match_ID'].notna())
    df_docs = df[mask_ids] # Belgeler
    df_others = df[~mask_ids] # Belgesizler (Ödemeler)
    
    # Gruplama (Belgeler İçin)
    df_grouped = pd.DataFrame()
    if not df_docs.empty:
        agg_rules = {
            'Tarih': 'first', 'Tarih_Odeme': 'first', 'Orijinal_Belge_No': 'first', 
            'Payment_ID': 'first', 'Kaynak': 'first', 'Borc': 'sum', 'Alacak': 'sum', 
            'Para_Birimi': 'first'
        }
        # Ekstra kolonları koru
        for col in df.columns:
            if col not in agg_rules and col not in ['Match_ID', 'Doviz_Tutari']:
                agg_rules[col] = 'first'
        
        # Döviz Toplama (SUM - Analiz Sonucu)
        if is_doviz_aktif:
            def get_fx_sum(sub):
                return sub['Doviz_Tutari'].sum()
            
            cols_need = ['Match_ID', 'Doviz_Tutari']
            df_sub = df_docs[cols_need].copy()
            df_grouped = df_docs.groupby('Match_ID', as_index=False).agg(agg_rules)
            
            # Apply işlemini hızlandır
            fx_sums = df_sub.groupby('Match_ID')['Doviz_Tutari'].sum().reset_index()
            df_grouped = pd.merge(df_grouped, fx_sums, on='Match_ID', how='left')
        else:
            df_grouped = df_docs.groupby('Match_ID', as_index=False).agg(agg_rules)
            df_grouped['Doviz_Tutari'] = 0.0

    return df_grouped, df_others

# --- 3. ARAYÜZ ---
st.title("⚖️ Mutabakat Pro V62 (Sadeleştirilmiş)")

# AYARLAR (Sadece Rol Seçimi Kaldı)
with st.expander("Ayarlar", expanded=True):
    rol_secimi = st.radio("Ticari Rolümüz:", ["Biz Alıcıyız", "Biz Satıcıyız"], horizontal=True)
rol_kodu = "Biz Alıcıyız" if "Alıcıyız" in rol_secimi else "Biz Satıcıyız"

st.divider()
col1, col2 = st.columns(2)

# --- DOSYA YÜKLEME VE SEÇİMLER ---
def render_ui(key_prefix, title, role_code):
    st.subheader(title)
    f = st.file_uploader("Dosya Yükle", type=["xlsx", "xls"], key=f"{key_prefix}_f")
    config = {'rol_kodu': role_code}
    extra = []
    
    if f:
        d = pd.read_excel(f)
        d = d.loc[:, ~d.columns.duplicated()]
        cols = ["Seçiniz..."] + d.columns.tolist()
        fname = f.name
        
        # Auto-Fill Helper
        def idx(suffix, default): return get_smart_index(cols, default, fname, suffix)
        
        config['tarih_col'] = st.selectbox("Tarih", cols, index=idx('tarih_col', "Tarih"), key=f"{key_prefix}_d1")
        config['belge_col'] = st.selectbox("Belge No (Eşleşme Anahtarı)", cols, index=idx('belge_col', "Belge No"), key=f"{key_prefix}_doc")
        
        st.info("Opsiyonel Alanlar")
        config['tarih_odeme_col'] = st.selectbox("Ödeme Tarihi / Valör", cols, index=idx('tarih_odeme_col', "Valör"), key=f"{key_prefix}_pd")
        config['odeme_ref_col'] = st.selectbox("Ödeme Referans / Dekont No", cols, index=idx('odeme_ref_col', "Referans"), key=f"{key_prefix}_ref")
        
        st.success("Tutar Ayarları")
        tip = st.radio("Tutar Tipi", ["Ayrı", "Tek"], index=0, key=f"{key_prefix}_r1", horizontal=True)
        config['tutar_tipi'] = "Tek Kolon" if tip=="Tek" else "Ayrı Kolonlar"
        
        if tip=="Tek":
            config['tutar_col'] = st.selectbox("Tutar", cols, index=idx('tutar_col', "Tutar"), key=f"{key_prefix}_amt")
        else:
            config['borc_col'] = st.selectbox("Borç", cols, index=idx('borc_col', "Borç"), key=f"{key_prefix}_b")
            config['alacak_col'] = st.selectbox("Alacak", cols, index=idx('alacak_col', "Alacak"), key=f"{key_prefix}_a")
            
        c_dv1, c_dv2 = st.columns(2)
        config['doviz_cinsi_col'] = c_dv1.selectbox("Para Birimi", cols, index=idx('doviz_cinsi_col', "PB"), key=f"{key_prefix}_cur")
        config['doviz_tutar_col'] = c_dv2.selectbox("Döviz Tutarı", cols, index=idx('doviz_tutar_col', "Döviz"), key=f"{key_prefix}_cur_amt")
        
        extra = st.multiselect("Rapora Eklenecek Sütunlar:", d.columns.tolist(), key=f"{key_prefix}_multi")
        
        # Kaydet
        if fname:
            prefs = {}
            for k, v in config.items(): 
                if v and v != "Seçiniz...": prefs[k] = v
            st.session_state['column_prefs'][fname] = prefs
            ayarlari_kaydet({fname: prefs})
            
        return d, config, extra
    return None, None, []

with col1:
    d1, cf1, ex1 = render_ui("biz", "🏢 Bizim Kayıtlar", rol_kodu)

with col2:
    d2, cf2, ex2 = render_ui("onlar", "🏭 Karşı Taraf", rol_kodu)

st.divider()

# --- ANALİZ MOTORU ---
if st.button("🚀 Analizi Başlat", type="primary", use_container_width=True):
    if d1 is not None and d2 is not None:
        try:
            start = time.time()
            with st.spinner('Eşleştiriliyor...'):
                # 1. VERİ HAZIRLA
                raw_biz, dv_biz = veri_hazirla(d1, cf1, "Biz", False, ex1)
                raw_onlar, dv_onlar = veri_hazirla(d2, cf2, "Onlar", False, ex2)
                doviz_raporda = dv_biz or dv_onlar
                
                # 2. GRUPLA VE AYIR
                # grp_ -> Match ID'si olanlar (Faturalar)
                # oth_ -> Match ID'si olmayanlar (Ödemeler/Diğer)
                grp_biz, oth_biz = grupla_ve_ayir(raw_biz, dv_biz)
                grp_onlar, oth_onlar = grupla_ve_ayir(raw_onlar, dv_onlar)
                
                # 3. ÖZET TABLO
                df_ozet = ozet_tablo_olustur(raw_biz, raw_onlar)
                
                # 4. EŞLEŞTİRME (BELGE NO BAZLI)
                # Karşı tarafı indeksle
                dict_onlar = {}
                matched_onlar_indices = set()
                
                for idx, row in grp_onlar.iterrows():
                    dict_onlar[row['Match_ID']] = row
                
                eslesenler = []
                un_biz_doc = []
                
                for idx, row in grp_biz.iterrows():
                    mid = row['Match_ID']
                    # Bizim net tutar
                    my_net = row['Borc'] - row['Alacak']
                    
                    if mid in dict_onlar:
                        aday = dict_onlar[mid]
                        matched_onlar_indices.add(mid)
                        
                        # Onların net tutarı
                        their_net = aday['Borc'] - aday['Alacak']
                        
                        # Fark Hesabı: Biz + Onlar (Çünkü kayıtlar zıt yönlü olmalı)
                        # Biz 100 (Borç), Onlar -100 (Alacak) -> Toplam 0 (OK)
                        # Eğer işaretler aynıysa (İkisi de 100), toplam 200 olur (Hata)
                        diff = my_net + their_net
                        
                        durum = "✅ Tam Eşleşme" if abs(diff) < 1.0 else "⚠️ Tutar Farkı"
                        
                        d = {
                            "Durum": durum, "Belge No": row['Orijinal_Belge_No'],
                            "Tarih (Biz)": safe_strftime(row['Tarih']), "Tarih (Onlar)": safe_strftime(aday['Tarih']),
                            "Tutar (Biz)": my_net, "Tutar (Onlar)": their_net, "Fark (TL)": diff
                        }
                        # Ekstra
                        for c in ex1: d[f"BİZ: {c}"] = str(row.get(c, ""))
                        for c in ex2: d[f"KARŞI: {c}"] = str(aday.get(c, ""))
                        eslesenler.append(d)
                    else:
                        # Bizde Var Onlarda Yok
                        d = {
                            "Durum": "🔴 Bizde Var", "Belge No": row['Orijinal_Belge_No'],
                            "Tarih": safe_strftime(row['Tarih']), "Tutar (Biz)": my_net
                        }
                        for c in ex1: d[f"BİZ: {c}"] = str(row.get(c, ""))
                        un_biz_doc.append(d)
                
                # Onlarda Olup Bizde Olmayanlar (Belge No)
                un_onlar_doc = []
                for mid, row in dict_onlar.items():
                    if mid not in matched_onlar_indices:
                        their_net = row['Borc'] - row['Alacak']
                        d = {
                            "Durum": "🔵 Onlarda Var", "Belge No": row['Orijinal_Belge_No'],
                            "Tarih": safe_strftime(row['Tarih']), "Tutar (Onlar)": their_net
                        }
                        for c in ex2: d[f"KARŞI: {c}"] = str(row.get(c, ""))
                        un_onlar_doc.append(d)

                # 5. EŞLEŞTİRME (ÖDEME / DİĞER)
                # oth_biz vs oth_onlar
                # Eşleştirme Anahtarları: 1. Referans (Payment_ID), 2. Tarih+Tutar
                
                matched_pay_onlar_idx = set()
                eslesen_pay = []
                
                # Indexleme
                pay_dict_ref = {}
                pay_dict_fuzzy = {} # Tarih+Tutar
                
                for idx, row in oth_onlar.iterrows():
                    # Ref
                    pid = row['Payment_ID']
                    if pid and len(pid)>2:
                        pay_dict_ref.setdefault(pid, []).append(idx)
                    
                    # Fuzzy (Tarih + Mutlak Tutar)
                    amt = abs(row['Borc'] - row['Alacak'])
                    d_str = safe_strftime(row['Tarih_Odeme'])
                    key = f"{d_str}_{round(amt, 2)}"
                    pay_dict_fuzzy.setdefault(key, []).append(idx)
                
                un_biz_pay = []
                
                for idx, row in oth_biz.iterrows():
                    found_idx = None
                    
                    # 1. Referansla Ara
                    pid = row['Payment_ID']
                    if pid and len(pid)>2 and pid in pay_dict_ref:
                        for i in pay_dict_ref[pid]:
                            if i not in matched_pay_onlar_idx: found_idx = i; break
                    
                    # 2. Fuzzy Ara (Ref yoksa)
                    if found_idx is None:
                        amt = abs(row['Borc'] - row['Alacak'])
                        d_str = safe_strftime(row['Tarih_Odeme'])
                        key = f"{d_str}_{round(amt, 2)}"
                        
                        if key in pay_dict_fuzzy:
                            for i in pay_dict_fuzzy[key]:
                                if i not in matched_pay_onlar_idx: found_idx = i; break
                        
                        # 3. Toleranslı Ara (±3 Gün)
                        if found_idx is None:
                             for i, prow in oth_onlar.iterrows():
                                 if i not in matched_pay_onlar_idx:
                                     p_amt = abs(prow['Borc'] - prow['Alacak'])
                                     if abs(amt - p_amt) < 0.1: # Tutar tutuyor
                                         if pd.notna(row['Tarih_Odeme']) and pd.notna(prow['Tarih_Odeme']):
                                             diff = abs((row['Tarih_Odeme'] - prow['Tarih_Odeme']).days)
                                             if diff <= 3: found_idx = i; break
                    
                    if found_idx is not None:
                        matched_pay_onlar_idx.add(found_idx)
                        aday = oth_onlar.loc[found_idx]
                        my_net = row['Borc'] - row['Alacak']
                        their_net = aday['Borc'] - aday['Alacak']
                        
                        d = {
                            "Durum": "✅ Ödeme Eşleşti",
                            "Tarih (Biz)": safe_strftime(row['Tarih']),
                            "Tarih (Onlar)": safe_strftime(aday['Tarih']),
                            "Tutar (Biz)": my_net, "Tutar (Onlar)": their_net,
                            "Ref (Biz)": pid
                        }
                        for c in ex1: d[f"BİZ: {c}"] = str(row.get(c, ""))
                        for c in ex2: d[f"KARŞI: {c}"] = str(aday.get(c, ""))
                        eslesen_pay.append(d)
                    else:
                        my_net = row['Borc'] - row['Alacak']
                        d = {
                            "Durum": "🔴 Bizde Var (Ödeme)", "Tarih": safe_strftime(row['Tarih']), "Tutar": my_net
                        }
                        for c in ex1: d[f"BİZ: {c}"] = str(row.get(c, ""))
                        un_biz_pay.append(d)

                # Onlarda Kalan Ödemeler
                un_onlar_pay = []
                for idx, row in oth_onlar.iterrows():
                    if idx not in matched_pay_onlar_idx:
                        their_net = row['Borc'] - row['Alacak']
                        d = {
                            "Durum": "🔵 Onlarda Var (Ödeme)", "Tarih": safe_strftime(row['Tarih']), "Tutar": their_net
                        }
                        for c in ex2: d[f"KARŞI: {c}"] = str(row.get(c, ""))
                        un_onlar_pay.append(d)

                # SONUÇLARI BİRLEŞTİR
                st.session_state['sonuclar'] = {
                    "ÖZET": df_ozet,
                    "Eşleşen Belgeler": pd.DataFrame(eslesenler),
                    "Eşleşen Diğer/Ödemeler": pd.DataFrame(eslesen_pay),
                    "Farklılar (Biz)": pd.concat([pd.DataFrame(un_biz_doc), pd.DataFrame(un_biz_pay)], ignore_index=True),
                    "Farklılar (Onlar)": pd.concat([pd.DataFrame(un_onlar_doc), pd.DataFrame(un_onlar_pay)], ignore_index=True)
                }
                st.session_state['analiz_yapildi'] = True
                st.success(f"Analiz Bitti! ({time.time()-start:.2f} sn)")

        except Exception as e:
            st.error(f"Bir hata oluştu: {e}")

# --- SONUÇLARI GÖSTER ---
if st.session_state.get('analiz_yapildi', False):
    res = st.session_state['sonuclar']
    
    # Excel İndir
    c1, c2 = st.columns(2)
    with c1: st.download_button("📥 Excel İndir (2 Sayfa: Özet/Detay)", excel_indir_tek_sayfa(res), "Mutabakat_Raporu.xlsx")
    
    # Tablolar
    t1, t2, t3, t4, t5 = st.tabs(["Özet", "Belge Eşleşmeleri", "Ödeme/Diğer Eşleşmeler", "Bizde Fazla", "Onlarda Fazla"])
    
    with t1: st.dataframe(res["ÖZET"], use_container_width=True)
    
    # Belge Eşleşmeleri (Renkli)
    with t2:
        df = res["Eşleşen Belgeler"]
        if not df.empty:
            # Hatalıları kırmızı, tamları yeşil yap
            def color_row(row):
                return ['background-color: #ffe6e6' if "⚠️" in row['Durum'] else '' for _ in row]
            st.dataframe(df.style.apply(color_row, axis=1), use_container_width=True)
        else: st.info("Kayıt yok")
        
    with t3: st.dataframe(res["Eşleşen Diğer/Ödemeler"], use_container_width=True)
    with t4: st.dataframe(res["Farklılar (Biz)"], use_container_width=True)
    with t5: st.dataframe(res["Farklılar (Onlar)"], use_container_width=True)
