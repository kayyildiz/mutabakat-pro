import streamlit as st
import pandas as pd
import re
import io
import time
import warnings
import json
import os

# Uyarıları gizle
warnings.filterwarnings("ignore")

# --- 1. AYARLAR VE GÜVENLİK ---
st.set_page_config(page_title="Mutabakat Pro", layout="wide")

if 'analiz_yapildi' not in st.session_state:
    st.session_state['analiz_yapildi'] = False
if 'sonuclar' not in st.session_state:
    st.session_state['sonuclar'] = {}

CONFIG_FILE = "ayarlar.json"

def ayarlari_yukle():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def ayarlari_kaydet(yeni_ayarlar):
    mevcut = ayarlari_yukle()
    mevcut.update(yeni_ayarlar)
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(mevcut, f, ensure_ascii=False, indent=4)
    except:
        pass

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
    if filename in st.session_state['column_prefs']:
        saved_col = st.session_state['column_prefs'][filename].get(key_suffix)
        if saved_col in options:
            return options.index(saved_col)
    for i, opt in enumerate(options):
        if str(opt).strip().lower() == target_name.lower():
            return i
    return 0

def get_default_multiselect(options, targets):
    defaults = []
    for opt in options:
        for t in targets:
            if str(t).lower() in str(opt).lower():
                defaults.append(opt)
    return list(set(defaults))

@st.cache_data
def belge_no_temizle(val):
    if isinstance(val, (pd.Series, list, tuple)):
        val = val.iloc[0] if hasattr(val, 'iloc') else val[0]
    if pd.isna(val):
        return ""
    s = str(val)
    res = ''.join(filter(str.isdigit, s))
    if res:
        return str(int(res))
    return ""

@st.cache_data
def referans_no_temizle(val):
    # Seri / liste geldiyse ilk elemanı al
    if isinstance(val, (pd.Series, list, tuple)):
        val = val.iloc[0] if hasattr(val, 'iloc') else val[0]

    if pd.isna(val):
        return ""

    # Excel'den gelen float referansları düzgün al
    if isinstance(val, float):
        s = f"{val:.0f}"
    else:
        s = str(val)

    # Sadece rakamları bırak
    s = re.sub(r'\D', '', s)

    # Baştaki 0'ları temizle
    s = s.lstrip('0')

    # Çok kısa olanları yok say
    if len(s) < 3:
        return ""

    return s

def safe_strftime(val):
    if isinstance(val, (pd.Series, list, tuple)):
        val = val.iloc[0] if hasattr(val, 'iloc') else val[0]
    if pd.isna(val):
        return ""
    try:
        return val.strftime('%d.%m.%Y')
    except:
        return ""

def apply_excel_styles(writer, sheet_name, df):
    from openpyxl.styles import Font
    try:
        worksheet = writer.sheets[sheet_name]
        bold_cols = ['Biz_Bakiye', 'Onlar_Bakiye', 'Kümüle_Fark', 'Durum', 'Fark (TL)']
        header = [cell.value for cell in worksheet[1]]
        for col_idx, col_name in enumerate(header, 1):
            column_letter = worksheet.cell(row=1, column=col_idx).column_letter
            worksheet.column_dimensions[column_letter].width = 20
            if col_name in bold_cols:
                col_letter = worksheet.cell(row=1, column=col_idx).column_letter
                for cell in worksheet[col_letter]:
                    if cell.row > 1:
                        cell.font = Font(bold=True)
    except:
        pass

def excel_indir_coklu(dfs_dict):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        for sheet_name, df in dfs_dict.items():
            safe_name = re.sub(r'[\\/*?:\[\]]', '-', str(sheet_name))[:30]
            df.to_excel(writer, index=False, sheet_name=safe_name)
            apply_excel_styles(writer, safe_name, df)
    return output.getvalue()

def excel_indir_tek_sayfa(dfs_dict):
    output = io.BytesIO()
    master_df = pd.DataFrame()
    for category, df in dfs_dict.items():
        if not df.empty:
            df_temp = df.copy()
            df_temp.insert(0, "Kategori", category)
            master_df = pd.concat([master_df, df_temp], ignore_index=True)
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        master_df.to_excel(writer, index=False, sheet_name='Tum_Mutabakat_Verisi')
        apply_excel_styles(writer, 'Tum_Mutabakat_Verisi', master_df)
    return output.getvalue()

def ozet_rapor_olustur(df_biz_raw, df_onlar_raw):
    biz = df_biz_raw.copy()
    biz['Yil_Ay'] = biz['Tarih'].dt.to_period('M')
    biz['Net'] = biz['Borc'] - biz['Alacak']
    grp_biz = biz.groupby(['Para_Birimi', 'Yil_Ay'])[['Borc', 'Alacak', 'Net']].sum().reset_index()
    grp_biz.columns = ['Para_Birimi', 'Yil_Ay', 'Biz_Borc', 'Biz_Alacak', 'Biz_Net']
    
    onlar = df_onlar_raw.copy()
    onlar['Yil_Ay'] = onlar['Tarih'].dt.to_period('M')
    onlar['Net'] = onlar['Borc'] - onlar['Alacak']
    grp_onlar = onlar.groupby(['Para_Birimi', 'Yil_Ay'])[['Borc', 'Alacak', 'Net']].sum().reset_index()
    grp_onlar.columns = ['Para_Birimi', 'Yil_Ay', 'Onlar_Borc', 'Onlar_Alacak', 'Onlar_Net']
    
    ozet = pd.merge(grp_biz, grp_onlar, on=['Para_Birimi', 'Yil_Ay'], how='outer').fillna(0)
    ozet = ozet.sort_values(['Para_Birimi', 'Yil_Ay'])
    
    ozet['Biz_Bakiye'] = ozet.groupby('Para_Birimi')['Biz_Net'].cumsum()
    ozet['Onlar_Bakiye'] = ozet.groupby('Para_Birimi')['Onlar_Net'].cumsum()
    ozet['Kümüle_Fark'] = ozet['Biz_Bakiye'] + ozet['Onlar_Bakiye']
    
    ozet['Yil_Ay'] = ozet['Yil_Ay'].astype(str)
    cols = ['Para_Birimi', 'Yil_Ay', 'Biz_Borc', 'Biz_Alacak', 'Biz_Bakiye', 
            'Onlar_Borc', 'Onlar_Alacak', 'Onlar_Bakiye', 'Kümüle_Fark']
    return ozet[cols]

def veri_hazirla(df, config, taraf_adi, extra_cols=None):
    if extra_cols is None:
        extra_cols = []

    # Aynı isimli kolonları temizle
    df = df.loc[:, ~df.columns.duplicated()]
    df_copy = df.copy()

    # --- 1) Ana tablo (fatura + ödeme karışık) ---
    df_new = pd.DataFrame()

    # Extra kolonlar
    for col in extra_cols:
        if col in df_copy.columns:
            df_new[col] = df_copy[col].astype(str)

    # Tarihler
    df_new['Tarih'] = pd.to_datetime(df_copy[config['tarih_col']], dayfirst=True, errors='coerce')

    if config.get('tarih_odeme_col') and config['tarih_odeme_col'] != "Seçiniz...":
        df_new['Tarih_Odeme'] = pd.to_datetime(
            df_copy[config['tarih_odeme_col']], dayfirst=True, errors='coerce'
        )
    else:
        df_new['Tarih_Odeme'] = df_new['Tarih']

    # Belge No / Match_ID
    df_new['Orijinal_Belge_No'] = df_copy[config['belge_col']].astype(str)
    df_new['Match_ID'] = df_new['Orijinal_Belge_No'].apply(
        lambda x: ''.join(filter(str.isdigit, str(x)))
    )
    df_new['Match_ID'] = df_new['Match_ID'].replace(r'^0+', '', regex=True)

    # Payment_ID (Ödeme Ref / Dekont)
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
        df_new['Doviz_Tutari'] = pd.to_numeric(
            df_copy[config['doviz_tutar_col']], errors='coerce'
        ).fillna(0).abs()
        doviz_aktif = True
    else:
        df_new['Doviz_Tutari'] = 0.0

    # Tutar
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

    # --- 2) Ödeme satırlarını ayır ---
    # Ödeme = Payment_ID dolu satırlar
    df_pay_final = df_new[df_new['Payment_ID'] != ""].copy()
    df_pay_final['unique_idx'] = df_pay_final.index  # ödeme eşleştirmede kullanılıyor

    # Fatura tarafı için (raw_biz/raw_onlar) df_new aynen dönüyor
    return df_new, df_pay_final, doviz_aktif

def grupla(df, is_doviz_aktif):
    if df.empty:
        return df
    mask_ids = df['Match_ID'] != ""
    df_ids = df[mask_ids]
    df_noids = df[~mask_ids]
    
    if df_ids.empty:
        return df_noids
    
    agg_rules = {
        'Tarih': 'first', 'Tarih_Odeme': 'first', 'Orijinal_Belge_No': 'first', 
        'Payment_ID': 'first', 'Kaynak': 'first', 'Borc': 'sum', 'Alacak': 'sum', 
        'Para_Birimi': 'first'
    }
    for col in df.columns:
        if col not in agg_rules and col not in ['Match_ID', 'unique_idx', 'Doviz_Tutari']:
            agg_rules[col] = 'first'
            
    if is_doviz_aktif:
        def get_real_fx(sub):
            nt = sub[~sub['Para_Birimi'].isin(['TRY', 'TL'])]
            if not nt.empty:
                return nt['Doviz_Tutari'].sum()
            return 0.0
        
        cols_needed = ['Match_ID', 'Para_Birimi', 'Doviz_Tutari']
        df_sub = df_ids[cols_needed].copy()
        
        df_grp = df_ids.groupby('Match_ID', as_index=False).agg(agg_rules)
        df_grp = df_grp.set_index('Match_ID')
        df_grp['Doviz_Tutari'] = df_sub.groupby('Match_ID').apply(get_real_fx)
        df_grp = df_grp.reset_index()
    else:
        df_grp = df_ids.groupby('Match_ID', as_index=False).agg(agg_rules)
        df_grp['Doviz_Tutari'] = 0.0
        
    final = pd.concat([df_grp, df_noids], ignore_index=True)
    final['unique_idx'] = final.index
    return final

# --- 3. ARAYÜZ ---
c_title, c_settings = st.columns([2, 1])
with c_title:
    st.title("Mutabakat Pro")
with c_settings:
    rol_secimi = st.radio("Ticari Rolümüz:", ["Biz Alıcıyız", "Biz Satıcıyız"], horizontal=True)

rol_kodu = "Biz Alıcıyız" if "Alıcıyız" in rol_secimi else "Biz Satıcıyız"

st.divider()
col1, col2 = st.columns(2)

# SOL
with col1:
    st.subheader("🏢 Bizim Kayıtlar")
    f1 = st.file_uploader("Dosya", type=["xlsx", "xls"], key="f1")
    cf1 = {'rol_kodu': rol_kodu}
    ex_biz = [] 
    if f1:
        d1 = pd.read_excel(f1)
        d1 = d1.loc[:, ~d1.columns.duplicated()]
        cl1 = ["Seçiniz..."] + d1.columns.tolist()
        f_name1 = f1.name
        
        def_tarih = get_smart_index(cl1, "Tarih", f_name1, 'tarih_col')
        def_belge = get_smart_index(cl1, "Belge No", f_name1, 'belge_col')
        def_tutar = get_smart_index(cl1, "Tutar", f_name1, 'tutar_col')
        def_pb = get_smart_index(cl1, "PB", f_name1, 'doviz_cinsi_col')
        def_dt = get_smart_index(cl1, "Döviz", f_name1, 'doviz_tutar_col')

        cf1['tarih_col'] = st.selectbox("Tarih", cl1, index=def_tarih, key="d1")
        cf1['belge_col'] = st.selectbox("Belge No (Eşleşme Anahtarı)", cl1, index=def_belge, key="doc1")
        
        st.info("📅 Ödeme / Referans (Opsiyonel)")
        def_pod = get_smart_index(cl1, "Ödeme Tarihi", f_name1, 'tarih_odeme_col')
        def_ref = get_smart_index(cl1, "Referans", f_name1, 'odeme_ref_col')
        cf1['tarih_odeme_col'] = st.selectbox("Ödeme Tarihi (Valör)", cl1, index=def_pod, key="pd1")
        cf1['odeme_ref_col'] = st.selectbox("Ödeme Ref / Dekont No", cl1, index=def_ref, key="pref1")
        
        st.success("💰 Tutar")
        ty1 = st.radio("Tip", ["Ayrı", "Tek"], index=0, key="r1", horizontal=True)
        cf1['tutar_tipi'] = "Tek Kolon" if ty1 == "Tek" else "Ayrı Kolonlar"
        if ty1 == "Tek":
            cf1['tutar_col'] = st.selectbox("Tutar", cl1, index=def_tutar, key="amt1")
        else:
            def_b = get_smart_index(cl1, "Borç", f_name1, 'borc_col')
            def_a = get_smart_index(cl1, "Alacak", f_name1, 'alacak_col')
            cf1['borc_col'] = st.selectbox("Borç", cl1, index=def_b, key="b1")
            cf1['alacak_col'] = st.selectbox("Alacak", cl1, index=def_a, key="a1")
        c3, c4 = st.columns(2)
        cf1['doviz_cinsi_col'] = c3.selectbox("PB", cl1, index=def_pb, key="cur1")
        cf1['doviz_tutar_col'] = c4.selectbox("Döviz Tutar", cl1, index=def_dt, key="cur_amt1")
        ex_biz = st.multiselect("Rapora Eklenecek Sütunlar (Biz):", options=d1.columns.tolist(), key="multi1")

# SAĞ
with col2:
    st.subheader("🏭 Karşı Taraf")
    f2 = st.file_uploader("Dosya", type=["xlsx", "xls"], accept_multiple_files=True, key="f2")
    # Biz alıcıysak karşı taraf satıcı, biz satıcıysak karşı taraf alıcı gibi davranacak
    cf2 = {
        'rol_kodu': "Biz Satıcıyız" if rol_kodu == "Biz Alıcıyız" else "Biz Alıcıyız"
    }
    ex_onlar = []
    if f2:
        dfs = [pd.read_excel(f) for f in f2]
        d2 = pd.concat(dfs, ignore_index=True)
        d2 = d2.loc[:, ~d2.columns.duplicated()]
        cl2 = ["Seçiniz..."] + d2.columns.tolist()
        f_name2 = "merged_files" if len(f2) > 1 else f2[0].name
        
        def_tarih2 = get_smart_index(cl2, "Tarih", f_name2, 'tarih_col')
        def_belge2 = get_smart_index(cl2, "Fatura No", f_name2, 'belge_col')
        
        cf2['tarih_col'] = st.selectbox("Tarih", cl2, index=def_tarih2, key="d2")
        cf2['belge_col'] = st.selectbox("Belge No (Eşleşme Anahtarı)", cl2, index=def_belge2, key="doc2")
        
        st.info("📅 Ödeme / Referans (Opsiyonel)")
        def_pod2 = get_smart_index(cl2, "Ödeme Tarihi", f_name2, 'tarih_odeme_col')
        def_ref2 = get_smart_index(cl2, "Referans", f_name2, 'odeme_ref_col')
        cf2['tarih_odeme_col'] = st.selectbox("Ödeme Tarihi (Valör)", cl2, index=def_pod2, key="pd2")
        cf2['odeme_ref_col'] = st.selectbox("Ödeme Ref / Dekont No", cl2, index=def_ref2, key="pref2")
        
        st.success("💰 Tutar")
        ty2 = st.radio("Tip", ["Ayrı", "Tek"], index=0, key="r2", horizontal=True)
        cf2['tutar_tipi'] = "Tek Kolon" if ty2 == "Tek" else "Ayrı Kolonlar"
        if ty2 == "Tek":
            def_amt2 = get_smart_index(cl2, "Tutar", f_name2, 'tutar_col')
            cf2['tutar_col'] = st.selectbox("Tutar", cl2, index=def_amt2, key="amt2")
        else:
            def_b2 = get_smart_index(cl2, "Borç", f_name2, 'borc_col')
            def_a2 = get_smart_index(cl2, "Alacak", f_name2, 'alacak_col')
            cf2['borc_col'] = st.selectbox("Borç", cl2, index=def_b2, key="b2")
            cf2['alacak_col'] = st.selectbox("Alacak", cl2, index=def_a2, key="a2")
            
        c3, c4 = st.columns(2)
        def_pb2 = get_smart_index(cl2, "PB", f_name2, 'doviz_cinsi_col')
        def_dt2 = get_smart_index(cl2, "Döviz", f_name2, 'doviz_tutar_col')
        cf2['doviz_cinsi_col'] = c3.selectbox("PB", cl2, index=def_pb2, key="cur2")
        cf2['doviz_tutar_col'] = c4.selectbox("Döviz Tutar", cl2, index=def_dt2, key="cur_amt2")
        ex_onlar = st.multiselect("Rapora Eklenecek Sütunlar (Karşı):", options=d2.columns.tolist(), key="multi2")

st.divider()

st.divider()

# --- 4. ANALİZ MOTORU ---
if st.button("🚀 Başlat", type="primary", use_container_width=True):
    if f1 and f2:
        # HAFIZAYA KAYDET
        if f1.name:
            prefs = {}
            for k, v in cf1.items():
                if k in ['tarih_col', 'belge_col', 'tutar_col', 'borc_col', 'alacak_col',
                         'doviz_cinsi_col', 'doviz_tutar_col', 'tarih_odeme_col', 'odeme_ref_col']:
                    if v and v != "Seçiniz...":
                        prefs[k] = v
            st.session_state['column_prefs'][f1.name] = prefs
            ayarlari_kaydet({f1.name: prefs})
            
        f_name_right = "merged_files" if len(f2) > 1 else f2[0].name
        if f_name_right:
            prefs = {}
            for k, v in cf2.items():
                if k in ['tarih_col', 'belge_col', 'tutar_col', 'borc_col', 'alacak_col',
                         'doviz_cinsi_col', 'doviz_tutar_col', 'tarih_odeme_col', 'odeme_ref_col']:
                    if v and v != "Seçiniz...":
                        prefs[k] = v
            st.session_state['column_prefs'][f_name_right] = prefs
            ayarlari_kaydet({f_name_right: prefs})

        try:
            start = time.time()
            with st.spinner('İşleniyor...'):
                # 1. HAZIRLIK – 4 argüman (df, config, taraf, extra_cols)
                raw_biz, pay_biz, dv_biz = veri_hazirla(d1, cf1, "Biz", ex_biz)
                grp_biz = grupla(raw_biz, dv_biz)

                raw_onlar, pay_onlar, dv_onlar = veri_hazirla(d2, cf2, "Onlar", ex_onlar)
                grp_onlar = grupla(raw_onlar, dv_onlar)

                # Döviz raporda kullanılacak mı?
                doviz_raporda = dv_biz or dv_onlar

                # ÖZET
                all_biz = pd.concat([raw_biz, pay_biz]) if not pay_biz.empty else raw_biz
                all_onlar = pd.concat([raw_onlar, pay_onlar]) if not pay_onlar.empty else raw_onlar
                df_ozet = ozet_rapor_olustur(all_biz, all_onlar)

                # =========================================================
                #  FATURA / BELGE EŞLEŞTİRME (EŞLEŞENLER)
                # =========================================================

                # Önce Match_ID kontrolü
                grp_biz["Match_ID"] = grp_biz["Match_ID"].fillna("").astype(str)
                grp_onlar["Match_ID"] = grp_onlar["Match_ID"].fillna("").astype(str)

                biz_mid_nonempty = grp_biz["Match_ID"].ne("").sum()
                onlar_mid_nonempty = grp_onlar["Match_ID"].ne("").sum()

                eslesenler = []
                eslesen_odeme = []
                un_biz = []
                un_onlar = []

                # ------- 1) DEFAULT: Match_ID ile eşleştirme -------

                if biz_mid_nonempty > 0 and onlar_mid_nonempty > 0:
                    ortak_mid = set(grp_biz.loc[grp_biz["Match_ID"] != "", "Match_ID"]) & \
                                set(grp_onlar.loc[grp_onlar["Match_ID"] != "", "Match_ID"])

                    st.caption(
                        f"[Match_ID] Biz (boş olmayan): {biz_mid_nonempty} | "
                        f"Onlar (boş olmayan): {onlar_mid_nonempty} | "
                        f"Ortak Match_ID sayısı: {len(ortak_mid)}"
                    )

                    biz_m = grp_biz[grp_biz["Match_ID"].isin(ortak_mid)].copy()
                    onlar_m = grp_onlar[grp_onlar["Match_ID"].isin(ortak_mid)].copy()

                    merged = biz_m.merge(
                        onlar_m,
                        on="Match_ID",
                        how="inner",
                        suffixes=("_Biz", "_Onlar")
                    )

                else:
                    # ------- 2) FALLBACK: Orijinal_Belge_No ile eşleştirme -------
                    grp_biz["Merge_Key"] = grp_biz["Orijinal_Belge_No"].astype(str).str.upper().str.strip().str.replace(" ", "", regex=False)
                    grp_onlar["Merge_Key"] = grp_onlar["Orijinal_Belge_No"].astype(str).str.upper().str.strip().str.replace(" ", "", regex=False)

                    biz_key_nonempty = grp_biz["Merge_Key"].ne("").sum()
                    onlar_key_nonempty = grp_onlar["Merge_Key"].ne("").sum()
                    ortak_key = set(grp_biz.loc[grp_biz["Merge_Key"] != "", "Merge_Key"]) & \
                                set(grp_onlar.loc[grp_onlar["Merge_Key"] != "", "Merge_Key"])

                    st.caption(
                        f"[Fallback: Orijinal_Belge_No] Biz (boş olmayan): {biz_key_nonempty} | "
                        f"Onlar (boş olmayan): {onlar_key_nonempty} | "
                        f"Ortak Belge No sayısı: {len(ortak_key)}"
                    )

                    biz_m = grp_biz[grp_biz["Merge_Key"].isin(ortak_key)].copy()
                    onlar_m = grp_onlar[grp_onlar["Merge_Key"].isin(ortak_key)].copy()

                    merged = biz_m.merge(
                        onlar_m,
                        on="Merge_Key",
                        how="inner",
                        suffixes=("_Biz", "_Onlar")
                    )

                matched_biz_idx = set()
                matched_onlar_idx = set()

                # Eğer merged tamamen boşsa bile, aşağıda "Bizde Var / Onlarda Var" yine dolacak
                for _, m in merged.iterrows():
                    my_amt = m["Borc_Biz"] - m["Alacak_Biz"]
                    their_amt_raw = m["Borc_Onlar"] - m["Alacak_Onlar"]
                    mid = m.get("Match_ID", "")
                    display_their = their_amt_raw
                    display_date = m["Tarih_Onlar"]

                    if mid:
                        cand = raw_onlar[raw_onlar["Match_ID"] == mid]
                        if not cand.empty:
                            cand["net"] = cand["Borc"] - cand["Alacak"]
                            pozitif = cand[cand["net"] > 0]
                            
                            if not pozitif.empty:
                                best = pozitif.iloc[0]
                                display_their = best["net"]
                                display_date = best["Tarih"]
                            else:
                                best = cand.iloc[0]
                                display_their = best["net"]
                                display_date = best["Tarih"]
                    real_diff = my_amt + display_their

                    status = "✅ Tam Eşleşme" if abs(real_diff) < 1 else "❌ Tutar Farkı"

                    d = {
                        "Durum": status,
                        "Belge No": m["Orijinal_Belge_No_Biz"],
                        "Tarih (Biz)": safe_strftime(m["Tarih_Biz"]),
                        "Tarih (Onlar)": safe_strftime(display_date),
                        "Tutar (Biz)": my_amt,
                        "Tutar (Onlar)": display_their,
                        "Fark (TL)": real_diff,
                    }

                    if doviz_raporda:
                        dv_biz_val = float(m.get("Doviz_Tutari_Biz", 0) or 0)
                        dv_onlar_val = float(m.get("Doviz_Tutari_Onlar", 0) or 0)
                        d["PB"] = m["Para_Birimi_Biz"]
                        d["Döviz (Biz)"] = dv_biz_val
                        d["Döviz (Onlar)"] = dv_onlar_val
                        d["Fark (Döviz)"] = dv_biz_val - dv_onlar_val

                    eslesenler.append(d)
                    matched_biz_idx.add(m["unique_idx_Biz"])
                    matched_onlar_idx.add(m["unique_idx_Onlar"])

                # --------- BİZDE VAR (FATURA) -----------------
                for _, row_b in grp_biz.iterrows():
                    if row_b["unique_idx"] not in matched_biz_idx:
                        amt = row_b["Borc"] - row_b["Alacak"]
                        d_un = {
                            "Durum": "🔴 Bizde Var",
                            "Belge No": row_b["Orijinal_Belge_No"],
                            "Tarih": safe_strftime(row_b["Tarih"]),
                            "Tutar (Biz)": amt,
                        }
                        for c in ex_biz:
                            d_un[f"BİZ: {c}"] = str(row_b.get(c, ""))
                        un_biz.append(d_un)

                # --------- ONLARDA VAR (FATURA) -----------------
                for _, row_o in grp_onlar.iterrows():
                    if row_o["unique_idx"] not in matched_onlar_idx:
                        amt = row_o["Borc"] - row_o["Alacak"]
                        d_un = {
                            "Durum": "🔵 Onlarda Var",
                            "Belge No": row_o["Orijinal_Belge_No"],
                            "Tarih": safe_strftime(row_o["Tarih"]),
                            "Tutar (Onlar)": amt,
                        }
                        for c in ex_onlar:
                            d_un[f"KARŞI: {c}"] = str(row_o.get(c, ""))
                        un_onlar.append(d_un)

                # =========================================================
                #  ÖDEME EŞLEŞTİRME (REF / TUTAR / PB)
                # =========================================================
                if not pay_biz.empty and not pay_onlar.empty:
                    dict_onlar_pay_by_ref = {}
                    dict_onlar_pay_by_amt = {}

                    # Karşı taraf ödemelerini sözlüklere dağıt
                    for idx, r in pay_onlar.iterrows():
                        pid = r.get("Payment_ID", "")
                        amt = abs(r["Borc"] - r["Alacak"])
                        cur = r.get("Para_Birimi", "TRY")

                        if pid:
                            dict_onlar_pay_by_ref.setdefault(pid, []).append(idx)

                        dict_onlar_pay_by_amt.setdefault((amt, cur), []).append(idx)

                    used = set()
                    
                    # Bizim ödemeleri tek tek eşleştir
                    for idx, row_p in pay_biz.iterrows():
                        biz_pid = row_p.get("Payment_ID", "")
                        biz_amt = abs(row_p["Borc"] - row_p["Alacak"])
                        biz_cur = row_p.get("Para_Birimi", "TRY")

                        found_idx = None

                        # 1) Öncelik: Ref no eşleşmesi
                        if biz_pid and biz_pid in dict_onlar_pay_by_ref:
                            for i in dict_onlar_pay_by_ref[biz_pid]:
                                if i not in used:
                                    found_idx = i
                                    break

                        # 2) Tutar + PB eşleşmesi
                        if found_idx is None:
                            key = (biz_amt, biz_cur)
                            if key in dict_onlar_pay_by_amt:
                                for i in dict_onlar_pay_by_amt[key]:
                                    if i not in used:
                                        found_idx = i
                                        break

                        # EŞLEŞME BULUNDU
                        if found_idx is not None:
                            used.add(found_idx)
                            row_onlar = pay_onlar.loc[found_idx]

                            onlar_amt = abs(row_onlar["Borc"] - row_onlar["Alacak"])
                            fark_tl = biz_amt - onlar_amt

                            kayit = {
                                "Durum": "✅ Ödeme Eşleşti" if abs(fark_tl) < 0.01 else "🟡 Tutar Farkı",
                                "Ödeme Ref": biz_pid or row_onlar.get("Payment_ID", ""),
                                "Tarih (Biz)": safe_strftime(row_p.get("Tarih_Odeme", row_p["Tarih"])),
                                "Tarih (Onlar)": safe_strftime(row_onlar.get("Tarih_Odeme", row_onlar["Tarih"])),
                                "Tutar (Biz)": biz_amt,
                                "Tutar (Onlar)": onlar_amt,
                                "Fark (TL)": fark_tl,
                                "PB": biz_cur,
                            }

                            for c in ex_biz:
                                kayit[f"BİZ: {c}"] = str(row_p.get(c, ""))
                            for c in ex_onlar:
                                kayit[f"KARŞI: {c}"] = str(row_onlar.get(c, ""))

                            eslesen_odeme.append(kayit)

                        else:
                            d_un = {
                                "Durum": "🔴 Bizde Var (Ödeme)",
                                "Ödeme Ref": biz_pid,
                                "Tarih": safe_strftime(row_p.get("Tarih_Odeme", row_p["Tarih"])),
                                "Tutar": biz_amt,
                                "PB": biz_cur,
                            }
                            for c in ex_biz:
                                d_un[f"BİZ: {c}"] = str(row_p.get(c, ""))
                            un_biz.append(d_un)

                    # Karşı taraftaki eşleşmeyen ödemeler
                    for idx, r in pay_onlar.iterrows():
                        if idx not in used:
                            d_un = {
                                "Durum": "🔵 Onlarda Var (Ödeme)",
                                "Ödeme Ref": r.get("Payment_ID", ""),
                                "Tarih": safe_strftime(r.get("Tarih_Odeme", r["Tarih"])),
                                "Tutar": abs(r["Borc"] - r["Alacak"]),
                                "PB": r.get("Para_Birimi", "TRY"),
                            }
                            for c in ex_onlar:
                                d_un[f"KARŞI: {c}"] = str(r.get(c, ""))
                            un_onlar.append(d_un)

                # --- SONUÇLARI SESSION'A YAZ ---
                st.session_state['sonuclar'] = {
                    "ozet": df_ozet,
                    "eslesen": pd.DataFrame(eslesenler),
                    "odeme": pd.DataFrame(eslesen_odeme),
                    "un_biz": pd.DataFrame(un_biz),
                    "un_onlar": pd.DataFrame(un_onlar)
                }
                st.session_state['analiz_yapildi'] = True
                st.success(f"Bitti! Süre: {time.time() - start:.2f} sn")

        except Exception as e:
            st.error(f"Hata: {e}")

# --- 5. SONUÇ EKRANI ---
if st.session_state.get('analiz_yapildi', False):
    res = st.session_state['sonuclar']
    
    df_es = res.get("eslesen", pd.DataFrame())
    
    dfs_exp = {
        "ÖZET_BAKIYE": res.get("ozet", pd.DataFrame()),
        "Eşleşenler": df_es,
        "Ödemeler": res.get("odeme", pd.DataFrame()),
        "Bizde Var - Yok": res.get("un_biz", pd.DataFrame()),
        "Onlarda Var - Yok": res.get("un_onlar", pd.DataFrame())
    }

    c1, c2 = st.columns(2)
    with c1:
        st.download_button("📥 İndir (Ayrı Sayfalar)", excel_indir_coklu(dfs_exp), "Rapor.xlsx")
    with c2:
        st.download_button("📥 İndir (Tek Liste)", excel_indir_tek_sayfa(dfs_exp), "Ozet.xlsx")
    
    t_heads = ["📈 Özet", "✅ Eşleşenler", "💰 Ödemeler", "🔴 Bizde Var", "🔵 Onlarda Var"]
    tabs = st.tabs(t_heads)
    
    def highlight_cols(x):
        return ['font-weight: bold' if col in ['Biz_Bakiye', 'Onlar_Bakiye', 'Kümüle_Fark'] else '' for col in x.index]
    
    with tabs[0]: 
        try:
            st.dataframe(res.get("ozet", pd.DataFrame()).style.apply(highlight_cols, axis=1).format(precision=2), use_container_width=True)
        except:
            st.dataframe(res.get("ozet", pd.DataFrame()), use_container_width=True)
            
    with tabs[1]: 
        if not df_es.empty:
            def color_row(row):
                return ['background-color: #ffe6e6' if "❌" in str(row['Durum']) else '' for _ in row]
            st.dataframe(df_es.style.apply(color_row, axis=1), use_container_width=True)
        else:
            st.info("Kayıt yok")
    
    with tabs[2]:
        st.dataframe(res.get("odeme", pd.DataFrame()), use_container_width=True)
    with tabs[3]:
        st.dataframe(res.get("un_biz", pd.DataFrame()), use_container_width=True)
    with tabs[4]:
        st.dataframe(res.get("un_onlar", pd.DataFrame()), use_container_width=True)

