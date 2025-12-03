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
    if isinstance(val, (pd.Series, list, tuple)):
        val = val.iloc[0] if hasattr(val, 'iloc') else val[0]
    if pd.isna(val):
        return ""
    if isinstance(val, float):
        val = f"{val:.0f}"
    s = str(val).strip().upper()
    s = re.sub(r'[^A-Z0-9]', '', s)
    s = s.lstrip('0')
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
    df = df.loc[:, ~df.columns.duplicated()]
    df_copy = df.copy()
    
    # Ödeme Ayrıştırma
    df_payments = pd.DataFrame()
    filter_col = config.get('odeme_turu_sutunu')
    filter_vals = config.get('odeme_turu_degerleri')
    
    if filter_col and filter_vals and filter_col in df_copy.columns:
        mask_payment = df_copy[filter_col].isin(filter_vals)
        df_payments = df_copy[mask_payment].copy()
        df_copy = df_copy[~mask_payment]
    
    df_new = pd.DataFrame()
    for col in extra_cols:
        if col in df_copy.columns:
            df_new[col] = df_copy[col].astype(str)

    df_new['Tarih'] = pd.to_datetime(df_copy[config['tarih_col']], dayfirst=True, errors='coerce')
    
    if config.get('tarih_odeme_col') and config['tarih_odeme_col'] != "Seçiniz...":
        df_new['Tarih_Odeme'] = pd.to_datetime(df_copy[config['tarih_odeme_col']], dayfirst=True, errors='coerce')
    else:
        df_new['Tarih_Odeme'] = df_new['Tarih']

    # Belge No
    df_new['Orijinal_Belge_No'] = df_copy[config['belge_col']].astype(str)
    df_new['Match_ID'] = df_new['Orijinal_Belge_No'].apply(lambda x: ''.join(filter(str.isdigit, str(x))))
    df_new['Match_ID'] = df_new['Match_ID'].replace(r'^0+', '', regex=True)
    
    # Payment ID
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

    # Ödeme Verisi Hazırla
    df_pay_final = pd.DataFrame()
    if not df_payments.empty:
        df_pay_final = df_new.iloc[0:0].copy()
        df_pay_final['Tarih'] = pd.to_datetime(df_payments[config['tarih_col']], dayfirst=True, errors='coerce')
        
        if config.get('tarih_odeme_col') and config['tarih_odeme_col'] != "Seçiniz...":
            df_pay_final['Tarih_Odeme'] = pd.to_datetime(df_payments[config['tarih_odeme_col']], dayfirst=True, errors='coerce')
        else:
            df_pay_final['Tarih_Odeme'] = df_pay_final['Tarih']

        if "Tek Kolon" in config['tutar_tipi']:
            col_name = config['tutar_col']
            ham = pd.to_numeric(df_payments[col_name], errors='coerce').fillna(0)
            # rol yukarıda Tek Kolon bloğunda tanımlandı
            if rol == "Biz Alıcıyız":
                df_pay_final['Borc'] = ham.where(ham > 0, 0)
                df_pay_final['Alacak'] = ham.where(ham < 0, 0).abs()
            else:
                df_pay_final['Alacak'] = ham.where(ham > 0, 0)
                df_pay_final['Borc'] = ham.where(ham < 0, 0).abs()
        else:
            df_pay_final['Borc'] = pd.to_numeric(df_payments[config['borc_col']], errors='coerce').fillna(0)
            df_pay_final['Alacak'] = pd.to_numeric(df_payments[config['alacak_col']], errors='coerce').fillna(0)
        
        if doviz_aktif:
            df_pay_final['Para_Birimi'] = df_payments[config['doviz_cinsi_col']].astype(str).str.upper().str.strip()
            df_pay_final['Para_Birimi'] = df_pay_final['Para_Birimi'].replace({'TL': 'TRY'})
            df_pay_final['Doviz_Tutari'] = pd.to_numeric(df_payments[config['doviz_tutar_col']], errors='coerce').fillna(0).abs()
        else:
            df_pay_final['Para_Birimi'] = "TRY"
            df_pay_final['Doviz_Tutari'] = 0.0
            
        for col in extra_cols:
            if col in df_payments.columns:
                df_pay_final[col] = df_payments[col].astype(str)
            
        df_pay_final['Match_ID'] = ""
        df_pay_final['Kaynak'] = taraf_adi
        df_pay_final['unique_idx'] = df_pay_final.index
        
        if config.get('odeme_ref_col') and config['odeme_ref_col'] != "Seçiniz...":
            df_pay_final['Payment_ID'] = df_payments[config['odeme_ref_col']].apply(referans_no_temizle)
        else:
            df_pay_final['Payment_ID'] = ""

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
    cf2 = {'rol_kodu': rol_kodu}
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

# --- 4. ANALİZ MOTORU ---
if st.button("🚀 Başlat", type="primary", use_container_width=True):
    if f1 and f2:
        # HAFIZAYA KAYDET
        if f1.name:
            prefs = {}
            for k, v in cf1.items():
                if k in ['tarih_col', 'belge_col', 'tutar_col', 'borc_col', 'alacak_col', 'doviz_cinsi_col', 'doviz_tutar_col', 'tarih_odeme_col', 'odeme_ref_col']:
                    if v and v != "Seçiniz...":
                        prefs[k] = v
            st.session_state['column_prefs'][f1.name] = prefs
            ayarlari_kaydet({f1.name: prefs})
            
        f_name_right = "merged_files" if len(f2) > 1 else f2[0].name
        if f_name_right:
            prefs = {}
            for k, v in cf2.items():
                if k in ['tarih_col', 'belge_col', 'tutar_col', 'borc_col', 'alacak_col', 'doviz_cinsi_col', 'doviz_tutar_col', 'tarih_odeme_col', 'odeme_ref_col']:
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
                
                doviz_raporda = dv_biz or dv_onlar
                
                # ÖZET
                all_biz = pd.concat([raw_biz, pay_biz]) if not pay_biz.empty else raw_biz
                all_onlar = pd.concat([raw_onlar, pay_onlar]) if not pay_onlar.empty else raw_onlar
                df_ozet = ozet_rapor_olustur(all_biz, all_onlar)
                
                # EŞLEŞTİRME SÖZLÜKLERİ
                matched_ids = set()
                dict_onlar_id = {}
                dict_onlar_tutar = {}
                
                for idx, row in grp_onlar.iterrows():
                    mid = row['Match_ID']
                    if mid:
                        if mid not in dict_onlar_id:
                            dict_onlar_id[mid] = []
                        dict_onlar_id[mid].append(row)
                    
                    amt = abs(row['Borc'] - row['Alacak'])
                    key_amt = f"{round(amt, 2)}_{row['Para_Birimi']}"
                    if key_amt not in dict_onlar_tutar:
                        dict_onlar_tutar[key_amt] = []
                    dict_onlar_tutar[key_amt].append(row)

                eslesenler = []
                eslesen_odeme = []
                un_biz = []
                
                # --- ANA EŞLEŞTİRME ---
                for idx, row in grp_biz.iterrows():
                    found = False
                    my_amt = row['Borc'] - row['Alacak']  # Net Bakiye
                    
                    if row['Match_ID'] and row['Match_ID'] in dict_onlar_id:
                        cands = dict_onlar_id[row['Match_ID']]
                        best = None
                        min_diff = float('inf')
                        
                        for c in cands:
                            if c['unique_idx'] not in matched_ids:
                                their_amt = c['Borc'] - c['Alacak']
                                diff = abs(my_amt + their_amt)  # zıt yön
                                if diff < min_diff:
                                    min_diff = diff
                                    best = c
                        
                        if best is not None:
                            matched_ids.add(best['unique_idx'])
                            their_amt = best['Borc'] - best['Alacak']
                            real_diff = my_amt + their_amt
                            
                            real_dv_diff = 0
                            if doviz_raporda:
                                real_dv_diff = row['Doviz_Tutari'] - best['Doviz_Tutari']

                            status = "✅ Tam Eşleşme" if min_diff < 1.0 else "❌ Tutar Farkı"
                            
                            d = {
                                "Durum": status,
                                "Belge No": row['Orijinal_Belge_No'],
                                "Tarih (Biz)": safe_strftime(row['Tarih']),
                                "Tarih (Onlar)": safe_strftime(best['Tarih']),
                                "Tutar (Biz)": my_amt,
                                "Tutar (Onlar)": their_amt,
                                "Fark (TL)": real_diff
                            }
                            if doviz_raporda:
                                d["PB"] = row['Para_Birimi']
                                d["Döviz (Biz)"] = row['Doviz_Tutari']
                                d["Döviz (Onlar)"] = best['Doviz_Tutari']
                                d["Fark (Döviz)"] = real_dv_diff
                                
                            for c in ex_biz:
                                d[f"BİZ: {c}"] = str(row.get(c, ""))
                            for c in ex_onlar:
                                d[f"KARŞI: {c}"] = str(best.get(c, ""))
                            
                            eslesenler.append(d)
                            found = True
                    
                    if not found:
                        d_un = {
                            "Durum": "🔴 Bizde Var",
                            "Belge No": row['Orijinal_Belge_No'],
                            "Tarih": safe_strftime(row['Tarih']),
                            "Tutar (Biz)": my_amt
                        }
                        for c in ex_biz:
                            d_un[f"BİZ: {c}"] = str(row.get(c, ""))
                        un_biz.append(d_un)

                un_onlar = []
                for idx, row in grp_onlar.iterrows():
                    if row['Match_ID'] and row['unique_idx'] not in matched_ids:
                        amt = row['Borc'] - row['Alacak']
                        d_un = {
                            "Durum": "🔵 Onlarda Var",
                            "Belge No": row['Orijinal_Belge_No'],
                            "Tarih": safe_strftime(row['Tarih']),
                            "Tutar (Onlar)": amt
                        }
                        for c in ex_onlar:
                            d_un[f"KARŞI: {c}"] = str(row.get(c, ""))
                        un_onlar.append(d_un)

                # ÖDEME EŞLEŞTİRME
                if not pay_biz.empty and not pay_onlar.empty:
                    dict_pay = {}
                    dict_pay_ref = {}
                    used_pay = set()
                    
                    for idx, row in pay_onlar.iterrows():
                        amt = abs(row['Borc'] - row['Alacak'])
                        key = f"{safe_strftime(row['Tarih_Odeme'])}_{round(amt, 2)}_{row['Para_Birimi']}"
                        dict_pay.setdefault(key, []).append(idx)
                        
                        pid = row['Payment_ID']
                        if pid and len(pid) > 2:
                            dict_pay_ref.setdefault(pid, []).append(idx)
                    
                    for idx, row in pay_biz.iterrows():
                        found_idx = None
                        amt = abs(row['Borc'] - row['Alacak'])
                        
                        # 1. Referans
                        pid = row['Payment_ID']
                        if pid and len(pid) > 2 and pid in dict_pay_ref:
                            for i in dict_pay_ref[pid]:
                                if i not in used_pay:
                                    found_idx = i
                                    break
                        
                        # 2. Tarih + Tutar
                        if found_idx is None:
                            key = f"{safe_strftime(row['Tarih_Odeme'])}_{round(amt, 2)}_{row['Para_Birimi']}"
                            if key in dict_pay:
                                for i in dict_pay[key]:
                                    if i not in used_pay:
                                        found_idx = i
                                        break
                            
                            # 3. Toleranslı eşleşme
                            if found_idx is None:
                                for i, prow in pay_onlar.iterrows():
                                    if i not in used_pay and prow['Para_Birimi'] == row['Para_Birimi']:
                                        p_amt = abs(prow['Borc'] - prow['Alacak'])
                                        if abs(amt - p_amt) < 0.1:
                                            if pd.notna(row['Tarih_Odeme']) and pd.notna(prow['Tarih_Odeme']):
                                                diff_days = abs((row['Tarih_Odeme'] - prow['Tarih_Odeme']).days)
                                                if diff_days <= 3:
                                                    found_idx = i
                                                    break
                        
                        if found_idx is not None:
                            used_pay.add(found_idx)
                            aday = pay_onlar.loc[found_idx]
                            d_pay = {
                                "Durum": "✅ Ödeme Eşleşti", 
                                "Tarih (Biz)": safe_strftime(row['Tarih']),
                                "Tutar (Biz)": amt,
                                "PB": row['Para_Birimi']
                            }
                            for c in ex_biz:
                                d_pay[f"BİZ: {c}"] = str(row.get(c, ""))
                            for c in ex_onlar:
                                d_pay[f"KARŞI: {c}"] = str(aday.get(c, ""))
                            eslesen_odeme.append(d_pay)
                        else:
                            d_un = {
                                "Durum": "🔴 Bizde Var (Ödeme)",
                                "Tarih": safe_strftime(row['Tarih']),
                                "Tutar": amt
                            }
                            un_biz.append(d_un)

                    # Onlarda kalan ödemeler
                    for idx, row in pay_onlar.iterrows():
                        if idx not in used_pay:
                            d_un = {
                                "Durum": "🔵 Onlarda Var (Ödeme)",
                                "Tarih": safe_strftime(row['Tarih']),
                                "Tutar": abs(row['Borc'] - row['Alacak'])
                            }
                            un_onlar.append(d_un)

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

