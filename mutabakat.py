import streamlit as st
import pandas as pd
import re
import io
import time
import warnings

# Uyarıları gizle
warnings.filterwarnings("ignore")

# --- 1. ARAYÜZ VE HAFIZA ---
st.set_page_config(page_title="Mutabakat Pro V50", layout="wide")

# --- SESSION STATE (HAFIZA) ---
if 'analiz_yapildi' not in st.session_state:
    st.session_state['analiz_yapildi'] = False
if 'sonuclar' not in st.session_state:
    st.session_state['sonuclar'] = {}
# Akıllı Hafıza: Dosya adına göre kolon seçimlerini hatırlar
if 'column_prefs' not in st.session_state:
    st.session_state['column_prefs'] = {}

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

def get_smart_index(options, target_name, filename, setting_key):
    """
    Önce hafızadaki tercihe bakar, yoksa isme göre tahmin eder.
    """
    # 1. Hafıza Kontrolü
    prefs = st.session_state['column_prefs'].get(filename, {})
    saved_col = prefs.get(setting_key)
    
    if saved_col and saved_col in options:
        return options.index(saved_col)
    
    # 2. Akıllı Tahmin (Hafıza yoksa)
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
    if pd.isna(val): return ""
    s = str(val)
    res = ''.join(filter(str.isdigit, s))
    if res: return str(int(res)) 
    return ""

@st.cache_data
def referans_no_temizle(val):
    if isinstance(val, (pd.Series, list, tuple)):
        val = val.iloc[0] if hasattr(val, 'iloc') else val[0]
    if pd.isna(val): return ""
    if isinstance(val, float): val = f"{val:.0f}"
    s = str(val).strip().upper()
    s = re.sub(r'[^A-Z0-9]', '', s)
    s = s.lstrip('0')
    return s

def safe_strftime(val):
    if isinstance(val, (pd.Series, list, tuple)):
        val = val.iloc[0] if hasattr(val, 'iloc') else val[0]
    if pd.isna(val): return ""
    try: return val.strftime('%d.%m.%Y')
    except: return ""

def excel_indir_coklu(dfs_dict):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        for sheet_name, df in dfs_dict.items():
            safe_name = re.sub(r'[\\/*?:\[\]]', '-', str(sheet_name))[:30]
            df.to_excel(writer, index=False, sheet_name=safe_name)
            worksheet = writer.sheets[safe_name]
            for column_cells in worksheet.columns:
                try:
                    val = column_cells[0].value
                    length = len(str(val)) if val else 0
                    worksheet.column_dimensions[column_cells[0].column_letter].width = min(length + 5, 50)
                except: pass
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

def veri_hazirla(df, config, taraf_adi, is_insurance_mode=False, extra_cols=[]):
    df = df.loc[:, ~df.columns.duplicated()]
    df_copy = df.copy()
    
    df_payments = pd.DataFrame()
    filter_col = config.get('odeme_turu_sutunu')
    filter_vals = config.get('odeme_turu_degerleri')
    
    if filter_col and filter_vals and filter_col in df_copy.columns:
        mask_payment = df_copy[filter_col].isin(filter_vals)
        df_payments = df_copy[mask_payment].copy()
        df_copy = df_copy[~mask_payment]
    
    df_new = pd.DataFrame()
    for col in extra_cols:
        if col in df_copy.columns: df_new[col] = df_copy[col].astype(str)

    df_new['Tarih'] = pd.to_datetime(df_copy[config['tarih_col']], dayfirst=True, errors='coerce')
    
    if not is_insurance_mode and config.get('tarih_odeme_col') and config['tarih_odeme_col'] != "Seçiniz...":
        df_new['Tarih_Odeme'] = pd.to_datetime(df_copy[config['tarih_odeme_col']], dayfirst=True, errors='coerce')
    else:
        df_new['Tarih_Odeme'] = df_new['Tarih']

    # Match ID
    if is_insurance_mode and taraf_adi == "Onlar":
        pol = config.get('police_col')
        zey = config.get('zeyil_col')
        if pol and zey:
            df_new['Orijinal_Belge_No'] = df_copy[pol].fillna('').astype(str) + " / " + df_copy[zey].fillna('').astype(str)
            def clean_join(p, z):
                if isinstance(p, pd.Series): p = p.iloc[0]
                if isinstance(z, pd.Series): z = z.iloc[0]
                p_c = ''.join(filter(str.isdigit, str(p)))
                z_c = ''.join(filter(str.isdigit, str(z)))
                if p_c: return str(int(p_c + z_c))
                return ""
            df_new['Match_ID'] = df_copy.apply(lambda x: clean_join(x.get(pol), x.get(zey)), axis=1)
        else:
            df_new['Match_ID'] = ""
            df_new['Orijinal_Belge_No'] = ""
    else:
        df_new['Orijinal_Belge_No'] = df_copy[config['belge_col']].astype(str)
        df_new['Match_ID'] = df_new['Orijinal_Belge_No'].apply(lambda x: ''.join(filter(str.isdigit, str(x))))
        df_new['Match_ID'] = df_new['Match_ID'].replace(r'^0+', '', regex=True)
    
    # Payment ID
    if not is_insurance_mode and config.get('odeme_ref_col') and config['odeme_ref_col'] != "Seçiniz...":
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

    df_pay_final = pd.DataFrame()
    if not df_payments.empty:
        df_pay_final = df_new.iloc[0:0].copy()
        df_pay_final['Tarih'] = pd.to_datetime(df_payments[config['tarih_col']], dayfirst=True, errors='coerce')
        
        if "Tek Kolon" in config['tutar_tipi']:
            col_name = config['tutar_col']
            ham = pd.to_numeric(df_payments[col_name], errors='coerce').fillna(0)
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
            if col in df_payments.columns: df_pay_final[col] = df_payments[col].astype(str)
            
        df_pay_final['Match_ID'] = ""
        df_pay_final['Kaynak'] = taraf_adi
        df_pay_final['unique_idx'] = df_pay_final.index

    return df_new, df_pay_final, doviz_aktif

def grupla(df, is_doviz_aktif):
    if df.empty: return df
    mask_ids = df['Match_ID'] != ""
    df_ids = df[mask_ids]
    df_noids = df[~mask_ids]
    
    if df_ids.empty: return df_noids
    
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
            if not nt.empty: return nt['Doviz_Tutari'].max()
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
with c_title: st.title("💎 Mutabakat Pro V50") # Yeni İkon
with c_settings:
    with st.expander("⚙️ Ayarlar", expanded=True):
        mode_selection = st.radio("Mod:", ["C/H Ekstresi", "Sigorta Poliçesi"])
        # Rol artık Dikey (horizontal=False sildik)
        rol_secimi = st.radio("Rol:", ["Biz Alıcıyız", "Biz Satıcıyız"])

rol_kodu = "Biz Alıcıyız" if "Alıcıyız" in rol_secimi else "Biz Satıcıyız"
is_ins = (mode_selection == "Sigorta Poliçesi")

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
        
        # AKILLI HAFIZA: Kayıtlı ismi bul
        f_name = f1.name
        
        # Auto-Fill Logic (Hafızadan veya Tahminden)
        def get_idx(key_suffix, default_guess):
            # Önce hafızaya bak
            if f_name in st.session_state['column_prefs']:
                saved = st.session_state['column_prefs'][f_name].get(key_suffix)
                if saved in cl1: return cl1.index(saved)
            # Yoksa tahmin et
            return get_default_idx(cl1, default_guess)

        def_tarih = get_idx('tarih_col', "Belge tarihi" if is_ins else "Tarih")
        def_belge = get_idx('belge_col', "Referans" if is_ins else "Belge No")
        def_tutar = get_idx('tutar_col', "Belge PB cinsinden tutar" if is_ins else "Tutar")
        
        cf1['tarih_col'] = st.selectbox("Tarih", cl1, index=def_tarih, key="d1")
        cf1['belge_col'] = st.selectbox("Belge No / Poliçe No", cl1, index=def_belge, key="doc1")
        
        if not is_ins:
            st.info("📅 Ödeme")
            def_pod = get_idx('tarih_odeme_col', "Ödeme Tarihi")
            def_ref = get_idx('odeme_ref_col', "Referans")
            cf1['tarih_odeme_col'] = st.selectbox("Ödeme Tarihi", cl1, index=def_pod, key="pd1")
            cf1['odeme_ref_col'] = st.selectbox("Ödeme Ref", cl1, index=def_ref, key="pref1")
        else:
            st.info("💳 Ödeme Filtresi")
            def_tur = get_idx('odeme_turu_sutunu', "Belge Türü Tanımı")
            fcol1 = st.selectbox("İşlem Türü:", cl1, index=def_tur, key="ftur1")
            if fcol1 and fcol1!="Seçiniz...":
                uv1 = d1[fcol1].astype(str).unique().tolist()
                dv1 = get_default_multiselect(uv1, ["Satıcı ödemesi", "HAVALE", "KREDI KARTI"])
                fv1 = st.multiselect("Ödeme Olanlar:", uv1, default=dv1, key="fvals1")
                cf1['odeme_turu_sutunu'] = fcol1
                cf1['odeme_turu_degerleri'] = fv1
        
        st.success("💰 Tutar")
        ty1 = st.radio("Tip", ["Ayrı", "Tek"], index=(1 if is_ins else 0), key="r1", horizontal=True)
        cf1['tutar_tipi'] = "Tek Kolon" if ty1=="Tek" else "Ayrı Kolonlar"
        if ty1=="Tek": cf1['tutar_col'] = st.selectbox("Tutar", cl1, index=def_tutar, key="amt1")
        else:
            def_b = get_idx('borc_col', "Borç")
            def_a = get_idx('alacak_col', "Alacak")
            cf1['borc_col'] = st.selectbox("Borç", cl1, index=def_b, key="b1")
            cf1['alacak_col'] = st.selectbox("Alacak", cl1, index=def_a, key="a1")
        
        c3, c4 = st.columns(2)
        def_pb = get_idx('doviz_cinsi_col', "PB")
        def_dt = get_idx('doviz_tutar_col', "Döviz Tutar")
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
        
        def get_idx2(key_suffix, default_guess):
            if f_name2 in st.session_state['column_prefs']:
                saved = st.session_state['column_prefs'][f_name2].get(key_suffix)
                if saved in cl2: return cl2.index(saved)
            return get_default_idx(cl2, default_guess)
        
        def_tarih2 = get_idx2('tarih_col', "İşlem Tarihi")
        cf2['tarih_col'] = st.selectbox("Tarih", cl2, index=def_tarih2, key="d2")
        
        if is_ins:
            c_p, c_z = st.columns(2)
            def_pol = get_idx2('police_col', "Poliçe No")
            def_zey = get_idx2('zeyil_col', "Zeyl No")
            cf2['police_col'] = c_p.selectbox("Poliçe No", cl2, index=def_pol, key="pol2")
            cf2['zeyil_col'] = c_z.selectbox("Zeyil No", cl2, index=def_zey, key="zey2")
            cf2['belge_col'] = ""
            
            st.markdown("---")
            st.info("💳 Ödeme Filtresi")
            def_ftur = get_idx2('odeme_turu_sutunu', "İşlem Türü")
            fcol = st.selectbox("İşlem Türü Sütunu:", cl2, index=def_ftur, key="ftur")
            if fcol and fcol != "Seçiniz...":
                uv = d2[fcol].astype(str).unique().tolist()
                dv = get_default_multiselect(uv, ["HAVALE", "KREDI KARTI"])
                fv = st.multiselect("Ödeme Olanlar:", uv, default=dv, key="fvals")
                cf2['odeme_turu_sutunu'] = fcol
                cf2['odeme_turu_degerleri'] = fv
        else:
            def_doc2 = get_idx2('belge_col', "Fatura No")
            cf2['belge_col'] = st.selectbox("Fatura/Belge No", cl2, index=def_doc2, key="doc2")
            st.info("📅 Ödeme")
            def_pod2 = get_idx2('tarih_odeme_col', "Ödeme Tarihi")
            def_ref2 = get_idx2('odeme_ref_col', "Referans")
            cf2['tarih_odeme_col'] = st.selectbox("Ödeme Tarihi", cl2, index=def_pod2, key="pd2")
            cf2['odeme_ref_col'] = st.selectbox("Ödeme Ref", cl2, index=def_ref2, key="pref2")

        st.success("💰 Tutar")
        ty2 = st.radio("Tip", ["Ayrı", "Tek"], index=(1 if is_ins else 0), key="r2", horizontal=True)
        cf2['tutar_tipi'] = "Tek Kolon" if ty2=="Tek" else "Ayrı Kolonlar"
        if ty2=="Tek": 
            def_amt2 = get_idx2('tutar_col', "Tutar_Döviz")
            cf2['tutar_col'] = st.selectbox("Tutar", cl2, index=def_amt2, key="amt2")
        else:
            def_b2 = get_idx2('borc_col', "Borç")
            def_a2 = get_idx2('alacak_col', "Alacak")
            cf2['borc_col'] = st.selectbox("Borç", cl2, index=def_b2, key="b2")
            cf2['alacak_col'] = st.selectbox("Alacak", cl2, index=def_a2, key="a2")
            
        c3, c4 = st.columns(2)
        def_pb2 = get_idx2('doviz_cinsi_col', "Para Cinsi")
        def_dt2 = get_idx2('doviz_tutar_col', "Tutar_Döviz")
        cf2['doviz_cinsi_col'] = c3.selectbox("PB", cl2, index=def_pb2, key="cur2")
        cf2['doviz_tutar_col'] = c4.selectbox("Döviz Tutar", cl2, index=def_dt2, key="cur_amt2")
        ex_onlar = st.multiselect("Rapora Eklenecek Sütunlar (Karşı):", options=d2.columns.tolist(), key="multi2")

st.divider()

if st.button("🚀 Başlat", type="primary", use_container_width=True):
    if f1 and f2:
        # SEÇİMLERİ HAFIZAYA KAYDET (AKILLI HAFIZA)
        # Sol
        if f1.name:
            prefs = {}
            for k, v in cf1.items():
                if k in ['tarih_col', 'belge_col', 'tutar_col', 'borc_col', 'alacak_col', 'doviz_cinsi_col', 'doviz_tutar_col', 'tarih_odeme_col', 'odeme_ref_col', 'odeme_turu_sutunu']:
                    if v and v != "Seçiniz...": prefs[k] = v
            st.session_state['column_prefs'][f1.name] = prefs
            
        # Sağ
        f_name_right = "merged_files" if len(f2) > 1 else f2[0].name
        if f_name_right:
            prefs = {}
            for k, v in cf2.items():
                if k in ['tarih_col', 'belge_col', 'police_col', 'zeyil_col', 'tutar_col', 'borc_col', 'alacak_col', 'doviz_cinsi_col', 'doviz_tutar_col', 'tarih_odeme_col', 'odeme_ref_col', 'odeme_turu_sutunu']:
                    if v and v != "Seçiniz...": prefs[k] = v
            st.session_state['column_prefs'][f_name_right] = prefs

        try:
            start = time.time()
            with st.spinner('İşleniyor...'):
                raw_biz, pay_biz, dv_biz = veri_hazirla(d1, cf1, "Biz", is_ins, ex_biz)
                grp_biz = grupla(raw_biz, dv_biz)
                
                raw_onlar, pay_onlar, dv_onlar = veri_hazirla(d2, cf2, "Onlar", is_ins, ex_onlar)
                grp_onlar = grupla(raw_onlar, dv_onlar)
                
                doviz_raporda = dv_biz or dv_onlar
                
                all_biz = pd.concat([raw_biz, pay_biz])
                all_onlar = pd.concat([raw_onlar, pay_onlar])
                df_ozet = ozet_rapor_olustur(all_biz, all_onlar)
                
                matched_ids = set()
                dict_onlar_id = {}
                dict_onlar_tutar = {}
                
                for idx, row in grp_onlar.iterrows():
                    mid = row['Match_ID']
                    if mid:
                        if mid not in dict_onlar_id: dict_onlar_id[mid] = []
                        dict_onlar_id[mid].append(row)
                    
                    amt = abs(row['Borc'] - row['Alacak'])
                    key_amt = f"{round(amt, 2)}_{row['Para_Birimi']}"
                    if key_amt not in dict_onlar_tutar: dict_onlar_tutar[key_amt] = []
                    dict_onlar_tutar[key_amt].append(row)

                eslesenler = []
                eslesen_odeme = []
                un_biz = []
                
                for idx, row in grp_biz.iterrows():
                    found = False
                    my_amt = abs(row['Borc'] - row['Alacak'])
                    
                    def make_row(durum, aday, fark_tl, fark_dv=0):
                        d = {
                            "Durum": durum, "Belge No": row['Orijinal_Belge_No'],
                            "Tarih (Biz)": safe_strftime(row['Tarih']), "Tarih (Onlar)": safe_strftime(aday['Tarih']),
                            "Tutar (Biz)": my_amt, "Tutar (Onlar)": abs(aday['Borc'] - aday['Alacak']),
                            "Fark (TL)": fark_tl
                        }
                        if doviz_raporda:
                            d["PB"] = row['Para_Birimi']
                            d["Döviz (Biz)"] = row['Doviz_Tutari']
                            d["Döviz (Onlar)"] = aday['Doviz_Tutari']
                            d["Fark (Döviz)"] = fark_dv
                        for c in ex_biz: d[f"BİZ: {c}"] = str(row.get(c, ""))
                        for c in ex_onlar: d[f"KARŞI: {c}"] = str(aday.get(c, ""))
                        return d

                    if is_ins:
                        # SIGORTA MODU
                        key = f"{round(my_amt, 2)}_{row['Para_Birimi']}"
                        if key in dict_onlar_tutar:
                            cands = dict_onlar_tutar[key]
                            best = None
                            for c in cands:
                                if c['unique_idx'] not in matched_ids:
                                    if pd.notna(row['Tarih']) and row['Tarih'] == c['Tarih']:
                                        best = c; break
                                    if best is None: best = c
                            if best:
                                matched_ids.add(best['unique_idx'])
                                eslesenler.append(make_row("✅ Tam Eşleşme", best, 0.0))
                                found = True

                        if not found and row['Match_ID']:
                            if row['Match_ID'] in dict_onlar_id:
                                cands = dict_onlar_id[row['Match_ID']]
                                best = None
                                min_diff = float('inf')
                                for c in cands:
                                    if c['unique_idx'] not in matched_ids:
                                        t_amt = abs(c['Borc'] - c['Alacak'])
                                        diff = abs(my_amt - t_amt)
                                        if diff < min_diff: min_diff = diff; best = c
                                
                                if best is not None:
                                    matched_ids.add(best['unique_idx'])
                                    diff_real = abs(my_amt) - abs(abs(best['Borc'] - best['Alacak']))
                                    real_dv = 0
                                    if doviz_raporda: real_dv = abs(row['Doviz_Tutari']) - abs(best['Doviz_Tutari'])
                                    status = "✅ Tam Eşleşme" if min_diff < 0.1 else "⚠️ Tutar Farkı"
                                    eslesenler.append(make_row(status, best, diff_real, real_dv))
                                    found = True
                    else:
                        # C/H MODU
                        if not found and row['Match_ID']:
                            if row['Match_ID'] in dict_onlar_id:
                                cands = dict_onlar_id[row['Match_ID']]
                                best = None
                                min_diff = float('inf')
                                for c in cands:
                                    if c['unique_idx'] not in matched_ids:
                                        t_amt = abs(c['Borc'] - c['Alacak'])
                                        diff = abs(my_amt - t_amt)
                                        if diff < min_diff: min_diff = diff; best = c
                                
                                if best is not None:
                                    matched_ids.add(best['unique_idx'])
                                    diff_real = my_amt - abs(best['Borc'] - best['Alacak'])
                                    status = "✅ Tam Eşleşme" if min_diff < 0.1 else "⚠️ Tutar Farkı"
                                    eslesenler.append(make_row(status, best, diff_real))
                                    found = True

                    if not found:
                        d_un = {
                            "Durum": "🔴 Bizde Var", "Belge No": row['Orijinal_Belge_No'],
                            "Tarih": safe_strftime(row['Tarih']), "Tutar": my_amt
                        }
                        for c in ex_biz: d_un[f"BİZ: {c}"] = str(row.get(c, ""))
                        un_biz.append(d_un)

                un_onlar = []
                for idx, row in grp_onlar.iterrows():
                    if row['unique_idx'] not in matched_ids:
                        amt = abs(row['Borc'] - row['Alacak'])
                        d_un = {
                            "Durum": "🔵 Onlarda Var", "Belge No": row['Orijinal_Belge_No'],
                            "Tarih": safe_strftime(row['Tarih']), "Tutar": amt
                        }
                        for c in ex_onlar: d_un[f"KARŞI: {c}"] = str(row.get(c, ""))
                        un_onlar.append(d_un)

                # ÖDEME EŞLEŞTİRME
                if not pay_biz.empty and not pay_onlar.empty:
                    dict_pay = {}
                    used_pay = set()
                    for idx, row in pay_onlar.iterrows():
                        amt = abs(row['Borc'] - row['Alacak'])
                        key = f"{safe_strftime(row['Tarih'])}_{round(amt, 2)}_{row['Para_Birimi']}"
                        if key not in dict_pay: dict_pay[key] = []
                        dict_pay[key].append(idx)
                    
                    for idx, row in pay_biz.iterrows():
                        amt = abs(row['Borc'] - row['Alacak'])
                        key = f"{safe_strftime(row['Tarih'])}_{round(amt, 2)}_{row['Para_Birimi']}"
                        if key in dict_pay:
                            found_idx = None
                            for i in dict_pay[key]:
                                if i not in used_pay: found_idx = i; break
                            if found_idx is not None:
                                used_pay.add(found_idx)
                                aday = pay_onlar.loc[found_idx]
                                eslesen_odeme.append({
                                    "Durum": "✅ Ödeme Eşleşti", "Tarih": safe_strftime(row['Tarih']),
                                    "Tutar": amt, "PB": row['Para_Birimi']
                                })

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
    # C/H Modunda hatalıları ayır
    if not df_es.empty:
        # Eğer Sigorta Modu değilse 1 TL kuralını uygula
        if not is_ins:
            # Fark (TL) kolonu varsa
            if 'Fark (TL)' in df_es.columns:
                df_ok = df_es[abs(df_es['Fark (TL)']) <= 1.0]
                df_err = df_es[abs(df_es['Fark (TL)']) > 1.0]
            else:
                df_ok = df_es
                df_err = pd.DataFrame()
        else:
            # Sigorta Modunda (Mutlak Eşleşme olduğu için) hatalıları yine de gösterebiliriz veya ayırabiliriz
            df_ok = df_es[~df_es['Durum'].str.contains('❌|⚠️', na=False)]
            df_err = df_es[df_es['Durum'].str.contains('❌|⚠️', na=False)]
    else:
        df_ok = pd.DataFrame()
        df_err = pd.DataFrame()

    dfs_exp = {
        "ÖZET_BAKIYE": res.get("ozet", pd.DataFrame()),
        "Eşleşen Poliçeler": df_ok,
        "Bizde Var - Yok": res.get("un_biz", pd.DataFrame()),
        "Onlarda Var - Yok": res.get("un_onlar", pd.DataFrame())
    }
    
    if not is_ins: 
        dfs_exp["Eşleşen Ödemeler"] = res.get("odeme", pd.DataFrame())
        # C/H modunda hatalıları ekle
        dfs_exp["Hatalı Farklar"] = df_err
    
    c1, c2 = st.columns(2)
    with c1: st.download_button("📥 İndir (Ayrı Sayfalar)", excel_indir_coklu(dfs_exp), "Rapor.xlsx")
    with c2: st.download_button("📥 İndir (Tek Liste)", excel_indir_tek_sayfa(dfs_exp), "Ozet.xlsx")
    
    t_list = ["📈 Özet", "✅ Eşleşenler"]
    if not is_ins: 
        t_list.append("⚠️ Hatalı Farklar (>1TL)")
        t_list.append("💰 Ödemeler")
        
    t_list.extend(["🔴 Bizde Var", "🔵 Onlarda Var"])
    
    tabs = st.tabs(t_list)
    
    # ÖZET (BOLD YAPILDI)
    with tabs[0]: 
        df_o = res.get("ozet", pd.DataFrame())
        # Pandas Styler ile Bold yap
        def highlight_cols(x):
            return ['font-weight: bold' if col in ['Biz_Bakiye', 'Onlar_Bakiye', 'Kümüle_Fark'] else '' for col in x.index]
        try:
            st.dataframe(df_o.style.apply(highlight_cols, axis=1).format(precision=2), use_container_width=True)
        except:
            st.dataframe(df_o, use_container_width=True)
            
    with tabs[1]: st.dataframe(df_ok, use_container_width=True)
    
    idx = 2
    if not is_ins:
        with tabs[idx]: st.dataframe(df_err, use_container_width=True)
        idx += 1
        with tabs[idx]: st.dataframe(res.get("odeme", pd.DataFrame()), use_container_width=True)
        idx += 1
        
    with tabs[idx]: st.dataframe(res.get("un_biz", pd.DataFrame()), use_container_width=True)
    with tabs[idx+1]: st.dataframe(res.get("un_onlar", pd.DataFrame()), use_container_width=True)
