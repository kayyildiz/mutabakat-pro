import streamlit as st
import pandas as pd
import re
import io
import time

# --- ARAYÜZ AYARLARI ---
st.set_page_config(page_title="Mutabakat Pro", layout="wide")

hide_st_style = """
            <style>
            #MainMenu {visibility: hidden;}
            header {visibility: hidden;}
            footer {visibility: hidden;}
            .stAppDeployButton {display:none;}
            [data-testid="stToolbar"] {visibility: hidden !important;}
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

# --- SESSION STATE (HAFIZA) BAŞLATMA ---
if 'analiz_yapildi' not in st.session_state:
    st.session_state['analiz_yapildi'] = False
if 'sonuclar' not in st.session_state:
    st.session_state['sonuclar'] = {}

# --- YARDIMCI FONKSİYONLAR ---

@st.cache_data
def belge_no_temizle(val):
    if pd.isna(val): return ""
    s = str(val)
    res = ''.join(filter(str.isdigit, s))
    if res: return str(int(s))
    return ""

@st.cache_data
def referans_no_temizle(val):
    if pd.isna(val): return ""
    s = str(val).strip().upper()
    s = re.sub(r'[^A-Z0-9]', '', s)
    s = s.lstrip('0')
    return s

def safe_strftime(val):
    if pd.isna(val): return ""
    try: return val.strftime('%d.%m.%Y')
    except: return ""

def excel_indir_coklu(dfs_dict):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        for sheet_name, df in dfs_dict.items():
            safe_name = re.sub(r'[\\/*?:\[\]]', '-', str(sheet_name))[:30]
            df.to_excel(writer, index=False, sheet_name=safe_name)
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

def ozet_rapor_olustur(df_biz, df_onlar):
    biz_monthly = df_biz.copy()
    biz_monthly['Yil_Ay'] = biz_monthly['Tarih'].dt.to_period('M')
    biz_monthly['Net_Hareket'] = biz_monthly['Borc'] - biz_monthly['Alacak']
    
    grp_biz = biz_monthly.groupby(['Para_Birimi', 'Yil_Ay'])[['Borc', 'Alacak', 'Net_Hareket']].sum().reset_index()
    grp_biz = grp_biz.rename(columns={'Borc': 'Biz_Borc', 'Alacak': 'Biz_Alacak', 'Net_Hareket': 'Biz_Net'})
    
    onlar_monthly = df_onlar.copy()
    onlar_monthly['Yil_Ay'] = onlar_monthly['Tarih'].dt.to_period('M')
    onlar_monthly['Net_Hareket'] = onlar_monthly['Borc'] - onlar_monthly['Alacak']
    
    grp_onlar = onlar_monthly.groupby(['Para_Birimi', 'Yil_Ay'])[['Borc', 'Alacak', 'Net_Hareket']].sum().reset_index()
    grp_onlar = grp_onlar.rename(columns={'Borc': 'Onlar_Borc', 'Alacak': 'Onlar_Alacak', 'Net_Hareket': 'Onlar_Net'})
    
    ozet = pd.merge(grp_biz, grp_onlar, on=['Para_Birimi', 'Yil_Ay'], how='outer').fillna(0)
    ozet = ozet.sort_values(['Para_Birimi', 'Yil_Ay'])
    
    ozet['Biz_Bakiye'] = ozet.groupby('Para_Birimi')['Biz_Net'].cumsum()
    ozet['Onlar_Bakiye'] = ozet.groupby('Para_Birimi')['Onlar_Net'].cumsum()
    ozet['Kümüle_Fark'] = ozet['Biz_Bakiye'] + ozet['Onlar_Bakiye']
    
    ozet['Yil_Ay'] = ozet['Yil_Ay'].astype(str)
    
    cols = ['Para_Birimi', 'Yil_Ay', 'Biz_Borc', 'Biz_Alacak', 'Biz_Bakiye', 
            'Onlar_Borc', 'Onlar_Alacak', 'Onlar_Bakiye', 'Kümüle_Fark']
    return ozet[cols]

def veri_hazirla_ve_grupla(df, config, taraf_adi, is_insurance_mode=False, extra_cols=[]):
    df_new = pd.DataFrame() 
    
    for col in extra_cols:
        if col in df.columns:
            df_new[col] = df[col].astype(str)

    df_new['Tarih'] = pd.to_datetime(df[config['tarih_col']], dayfirst=True, errors='coerce')
    
    if not is_insurance_mode and config.get('tarih_odeme_col') and config['tarih_odeme_col'] != "Seçiniz...":
        df_new['Tarih_Odeme'] = pd.to_datetime(df[config['tarih_odeme_col']], dayfirst=True, errors='coerce')
    else:
        df_new['Tarih_Odeme'] = df_new['Tarih']

    if is_insurance_mode and taraf_adi == "Onlar":
        pol = df[config['police_col']].fillna('').astype(str)
        zey = df[config['zeyil_col']].fillna('').astype(str)
        df_new['Orijinal_Belge_No'] = pol + " - " + zey
        
        def clean_join(p, z):
            p_clean = ''.join(filter(str.isdigit, str(p)))
            z_clean = ''.join(filter(str.isdigit, str(z)))
            if p_clean: 
                combined = p_clean + z_clean
                return str(int(combined)) if combined else ""
            return ""
        df_new['Match_ID'] = df.apply(lambda x: clean_join(x[config['police_col']], x[config['zeyil_col']]), axis=1)
    else:
        df_new['Orijinal_Belge_No'] = df[config['belge_col']].astype(str)
        df_new['Match_ID'] = df_new['Orijinal_Belge_No'].apply(lambda x: ''.join(filter(str.isdigit, str(x))))
        df_new['Match_ID'] = df_new['Match_ID'].replace(r'^0+', '', regex=True)
    
    if not is_insurance_mode and config.get('odeme_ref_col') and config['odeme_ref_col'] != "Seçiniz...":
        df_new['Payment_ID'] = df[config['odeme_ref_col']].apply(referans_no_temizle)
    else:
        df_new['Payment_ID'] = ""

    df_new['Kaynak'] = taraf_adi
    
    doviz_aktif = False
    if config.get('doviz_cinsi_col') and config['doviz_cinsi_col'] != "Seçiniz...":
        df_new['Para_Birimi'] = df[config['doviz_cinsi_col']].astype(str).str.upper().str.strip()
        df_new['Para_Birimi'] = df_new['Para_Birimi'].replace({'TL': 'TRY', 'TRL': 'TRY'})
        doviz_aktif = True
    else:
        df_new['Para_Birimi'] = "TRY"
        
    if config.get('doviz_tutar_col') and config['doviz_tutar_col'] != "Seçiniz...":
        df_new['Doviz_Tutari'] = pd.to_numeric(df[config['doviz_tutar_col']], errors='coerce').fillna(0).abs()
        doviz_aktif = True
    else:
        df_new['Doviz_Tutari'] = 0.0

    if "Tek Kolon" in config['tutar_tipi']:
        col_name = config['tutar_col']
        ham_tutar = pd.to_numeric(df[col_name], errors='coerce').fillna(0)
        
        if not doviz_aktif: df_new['Doviz_Tutari'] = 0.0
        
        rol = config.get('rol_kodu', 'Biz Alıcıyız') 
        if rol == "Biz Alıcıyız":
            df_new['Borc'] = ham_tutar.where(ham_tutar > 0, 0)
            df_new['Alacak'] = ham_tutar.where(ham_tutar < 0, 0).abs()
        else:
            df_new['Alacak'] = ham_tutar.where(ham_tutar > 0, 0)
            df_new['Borc'] = ham_tutar.where(ham_tutar < 0, 0).abs()
    else: 
        df_new['Borc'] = pd.to_numeric(df[config['borc_col']], errors='coerce').fillna(0)
        df_new['Alacak'] = pd.to_numeric(df[config['alacak_col']], errors='coerce').fillna(0)
    
    mask_ids = df_new['Match_ID'] != ""
    df_invoices = df_new[mask_ids]
    df_others = df_new[~mask_ids]
    
    mask_pay_ids = (df_others['Payment_ID'] != "") & (df_others['Payment_ID'].notna())
    df_payments = df_others[mask_pay_ids]
    df_rest = df_others[~mask_pay_ids]
    
    final_dfs = []
    agg_rules = {
        'Tarih': 'first', 'Tarih_Odeme': 'first', 'Orijinal_Belge_No': 'first', 
        'Kaynak': 'first', 'Borc': 'sum', 'Alacak': 'sum', 'Para_Birimi': 'first'
    }
    for col in extra_cols:
        if col in df_new.columns:
            agg_rules[col] = 'first'
    
    if doviz_aktif:
        def get_real_fx_amount(sub_df):
            non_try = sub_df[~sub_df['Para_Birimi'].isin(['TRY', 'TL', 'TRL'])]
            if not non_try.empty: return non_try['Doviz_Tutari'].max()
            else: return 0.0
        def get_real_fx_code(sub_df):
            non_try = sub_df[~sub_df['Para_Birimi'].isin(['TRY', 'TL', 'TRL'])]
            if not non_try.empty: return non_try['Para_Birimi'].iloc[0]
            return sub_df['Para_Birimi'].iloc[0]

    if not df_invoices.empty:
        df_grp_inv = df_invoices.groupby('Match_ID', as_index=False).agg(agg_rules)
        if not is_insurance_mode:
            df_grp_inv['Payment_ID'] = df_invoices.groupby('Match_ID')['Payment_ID'].first().values
        else:
            df_grp_inv['Payment_ID'] = ""

        if doviz_aktif:
            df_grp_inv = df_grp_inv.set_index('Match_ID')
            df_grp_inv['Doviz_Tutari'] = df_invoices.groupby('Match_ID').apply(get_real_fx_amount)
            df_grp_inv['Para_Birimi'] = df_invoices.groupby('Match_ID').apply(get_real_fx_code)
            df_grp_inv = df_grp_inv.reset_index()
        else:
            df_grp_inv['Doviz_Tutari'] = 0.0
        final_dfs.append(df_grp_inv)

    if not df_payments.empty:
        df_grp_pay = df_payments.groupby('Payment_ID', as_index=False).agg(agg_rules)
        df_grp_pay['Match_ID'] = "" 
        if doviz_aktif:
            df_grp_pay = df_grp_pay.set_index('Payment_ID')
            df_grp_pay['Doviz_Tutari'] = df_payments.groupby('Payment_ID').apply(get_real_fx_amount)
            df_grp_pay['Para_Birimi'] = df_payments.groupby('Payment_ID').apply(get_real_fx_code)
            df_grp_pay = df_grp_pay.reset_index()
        else:
            df_grp_pay['Doviz_Tutari'] = 0.0
        final_dfs.append(df_grp_pay)

    if not df_rest.empty:
        final_dfs.append(df_rest)

    if final_dfs:
        df_final = pd.concat(final_dfs, ignore_index=True)
    else:
        df_final = df_new
        
    df_final['unique_idx'] = df_final.index
    return df_final, doviz_aktif, df

# --- ARAYÜZ ---

st.title("🗂️ Mutabakat Pro")

col_mode1, col_mode2 = st.columns([1, 3])
with col_mode1:
    mode_selection = st.radio("Çalışma Modu:", ["C/H Ekstresi", "Sigorta Poliçesi"])
with col_mode2:
    rol_secimi = st.radio("Ticari Rolümüz:", ["Biz Alıcıyız", "Biz Satıcıyız"], horizontal=True)

rol_kodu = "Biz Alıcıyız" if "Alıcıyız" in rol_secimi else "Biz Satıcıyız"
is_insurance = (mode_selection == "Sigorta Poliçesi")

st.divider()
col1, col2 = st.columns(2)

with col1:
    st.subheader("🏢 Bizim Kayıtlar")
    file1 = st.file_uploader("Bizim Dosya", type=["xlsx", "xls"], key="f1")
    config1 = {'rol_kodu': rol_kodu}
    extra_cols_biz = [] 
    if file1:
        df1 = pd.read_excel(file1)
        with st.expander("Görünüm"): st.dataframe(df1.head(5), use_container_width=True)
        cols1 = ["Seçiniz..."] + df1.columns.tolist()
        c1, c2 = st.columns(2)
        with c1: config1['tarih_col'] = st.selectbox("Tarih", cols1[1:], key="d1")
        with c2: config1['belge_col'] = st.selectbox("Belge No / Poliçe No", cols1[1:], key="doc1")
        
        if not is_insurance:
            st.info("📅 Ödeme")
            config1['tarih_odeme_col'] = st.selectbox("Ödeme Tarihi (Valör)", cols1, key="pd1")
            config1['odeme_ref_col'] = st.selectbox("Ödeme Ref/Dekont No", cols1, key="pref1")
        
        st.success("💰 Tutar")
        tutar_yapi = st.radio("Tutar Tipi", ["Ayrı Kolonlar", "Tek Kolon"], key="r1", horizontal=True)
        config1['tutar_tipi'] = tutar_yapi
        if tutar_yapi == "Tek Kolon": config1['tutar_col'] = st.selectbox("Tutar", cols1[1:], key="amt1")
        else:
            c5, c6 = st.columns(2)
            with c5: config1['borc_col'] = st.selectbox("Borç", cols1[1:], key="b1")
            with c6: config1['alacak_col'] = st.selectbox("Alacak", cols1[1:], key="a1")
        c3, c4 = st.columns(2)
        with c3: config1['doviz_cinsi_col'] = st.selectbox("Para Birimi", cols1, key="cur1")
        with c4: config1['doviz_tutar_col'] = st.selectbox("Döviz Tutarı", cols1, key="cur_amt1")
        extra_cols_biz = st.multiselect("Rapora Eklenecek Sütunlar (Biz):", options=df1.columns.tolist(), key="multi1")

with col2:
    st.subheader("🏭 Karşı Taraf")
    files2 = st.file_uploader("Karşı Dosyalar", type=["xlsx", "xls"], accept_multiple_files=True, key="f2")
    config2 = {'rol_kodu': rol_kodu}
    extra_cols_onlar = []
    if files2:
        all_dfs = [pd.read_excel(f) for f in files2]
        df2 = pd.concat(all_dfs, ignore_index=True)
        with st.expander("Görünüm"): st.dataframe(df2.head(5), use_container_width=True)
        cols2 = ["Seçiniz..."] + df2.columns.tolist()
        c1, c2 = st.columns(2)
        with c1: config2['tarih_col'] = st.selectbox("Tarih", cols2[1:], key="d2")
        
        if is_insurance:
            st.warning("🔒 Sigorta Poliçesi Modu")
            c_pol, c_zey = st.columns(2)
            with c_pol: config2['police_col'] = st.selectbox("Poliçe No", cols2[1:], key="pol2")
            with c_zey: config2['zeyil_col'] = st.selectbox("Zeyil No", cols2[1:], key="zey2")
            config2['belge_col'] = ""
        else:
            with c2: config2['belge_col'] = st.selectbox("Fatura/Belge No", cols2[1:], key="doc2")
        
        if not is_insurance:
            st.info("📅 Ödeme")
            config2['tarih_odeme_col'] = st.selectbox("Ödeme Tarihi (Valör)", cols2, key="pd2")
            config2['odeme_ref_col'] = st.selectbox("Ödeme Ref/Dekont No", cols2, key="pref2")

        st.success("💰 Tutar")
        tutar_yapi2 = st.radio("Tutar Tipi", ["Ayrı Kolonlar", "Tek Kolon"], key="r2", horizontal=True)
        config2['tutar_tipi'] = tutar_yapi2
        if tutar_yapi2 == "Tek Kolon": config2['tutar_col'] = st.selectbox("Tutar", cols2[1:], key="amt2")
        else:
            c5, c6 = st.columns(2)
            with c5: config2['borc_col'] = st.selectbox("Borç", cols2[1:], key="b2")
            with c6: config2['alacak_col'] = st.selectbox("Alacak", cols2[1:], key="a2")
        c3, c4 = st.columns(2)
        with c3: config2['doviz_cinsi_col'] = st.selectbox("Para Birimi", cols2, key="cur2")
        with c4: config2['doviz_tutar_col'] = st.selectbox("Döviz Tutarı", cols2, key="cur_amt2")
        extra_cols_onlar = st.multiselect("Rapora Eklenecek Sütunlar (Karşı):", options=df2.columns.tolist(), key="multi2")

st.divider()

if st.button("🚀 Analizi Başlat", type="primary", use_container_width=True):
    if file1 and files2:
        try:
            start_time = time.time()
            with st.spinner('Veriler işleniyor...'):
                clean_biz, doviz_biz, orig_biz = veri_hazirla_ve_grupla(df1, config1, "Biz", is_insurance, extra_cols_biz)
                clean_onlar, doviz_onlar, orig_onlar = veri_hazirla_ve_grupla(df2, config2, "Onlar", is_insurance, extra_cols_onlar)
                
                df_ozet_rapor = ozet_rapor_olustur(clean_biz, clean_onlar)
                doviz_raporda = doviz_biz or doviz_onlar
                matched_onlar_indices = set()
                
                onlar_dict_id = {}
                onlar_dict_pay_id = {}
                onlar_dict_tutar = {}

                for idx, row in clean_onlar.iterrows():
                    mid = row['Match_ID']
                    if mid:
                        if mid not in onlar_dict_id: onlar_dict_id[mid] = []
                        onlar_dict_id[mid].append(row)
                    
                    if not is_insurance:
                        pid = row['Payment_ID']
                        if pid and len(pid) > 2:
                            if pid not in onlar_dict_pay_id: onlar_dict_pay_id[pid] = []
                            onlar_dict_pay_id[pid].append(row)
                        
                    val_borc = round(row['Borc'], 2)
                    val_alacak = round(row['Alacak'], 2)
                    curr = row['Para_Birimi']
                    
                    key_borc = f"{val_borc}_{curr}"
                    key_alacak = f"{val_alacak}_{curr}"
                    
                    if key_borc not in onlar_dict_tutar: onlar_dict_tutar[key_borc] = []
                    onlar_dict_tutar[key_borc].append(row)
                    if key_alacak not in onlar_dict_tutar: onlar_dict_tutar[key_alacak] = []
                    onlar_dict_tutar[key_alacak].append(row)

                eslesenler = []
                eslesen_odemeler = [] 
                unmatched_biz = []

                for idx, row in clean_biz.iterrows():
                    match_found = False
                    aranan_tutar = 0
                    aranan_yon = "" 
                    
                    if row['Borc'] > 0: aranan_tutar = row['Borc']; aranan_yon = 'Alacak'
                    elif row['Alacak'] > 0: aranan_tutar = row['Alacak']; aranan_yon = 'Borc'
                    
                    if aranan_tutar > 0:
                        
                        def make_row(durum, aday_row, real_fark_tl, real_fark_doviz=0):
                            data = {
                                "Durum": durum, "Belge No": row['Orijinal_Belge_No'],
                                "Tarih (Biz)": safe_strftime(row['Tarih']),
                                "Tarih (Onlar)": safe_strftime(aday_row['Tarih']),
                                "Tutar (Biz)": aranan_tutar, "Tutar (Onlar)": aday_row[aranan_yon],
                                "Fark (TL)": real_fark_tl
                            }
                            if doviz_raporda:
                                data["PB"] = row['Para_Birimi']
                                data["Döviz (Biz)"] = row['Doviz_Tutari']
                                data["Döviz (Onlar)"] = aday_row['Doviz_Tutari']
                                data["Fark (Döviz)"] = real_fark_doviz
                            
                            for c in extra_cols_biz:
                                data[f"BİZ: {c}"] = str(row.get(c, ""))
                            for c in extra_cols_onlar:
                                data[f"KARŞI: {c}"] = str(aday_row.get(c, ""))
                            
                            return data

                        # SİGORTA MODU
                        if is_insurance:
                            key = f"{round(aranan_tutar, 2)}_{row['Para_Birimi']}"
                            if key in onlar_dict_tutar:
                                candidates = onlar_dict_tutar[key]
                                unused = [c for c in candidates if c['unique_idx'] not in matched_onlar_indices]
                                best_match = None
                                for cand in (unused if unused else candidates):
                                    if pd.notna(row['Tarih']) and pd.notna(cand['Tarih']):
                                        if row['Tarih'] == cand['Tarih']: 
                                            best_match = cand
                                            break
                                if best_match is not None:
                                    matched_onlar_indices.add(best_match['unique_idx'])
                                    eslesen_odemeler.append(make_row("✅ Tarih/Tutar Eşleşmesi", best_match, 0.0, 0.0))
                                    match_found = True

                            mid = row['Match_ID']
                            if not match_found and mid and mid in onlar_dict_id:
                                candidates = onlar_dict_id[mid]
                                unused = [c for c in candidates if c['unique_idx'] not in matched_onlar_indices]
                                pool = unused if unused else candidates
                                best_candidate = None
                                min_diff_abs = float('inf')
                                for cand in pool:
                                    diff = abs(cand[aranan_yon] - aranan_tutar)
                                    if diff < min_diff_abs:
                                        min_diff_abs = diff
                                        best_candidate = cand
                                
                                if best_candidate is not None:
                                    match_found = True
                                    matched_onlar_indices.add(best_candidate['unique_idx'])
                                    real_fark_tl = aranan_tutar - best_candidate[aranan_yon]
                                    real_fark_doviz = 0
                                    
                                    durum = ""
                                    is_tl_match = min_diff_abs < 0.1
                                    is_doviz_match = True
                                    if doviz_raporda:
                                        real_fark_doviz = row['Doviz_Tutari'] - best_candidate['Doviz_Tutari']
                                        is_try = row['Para_Birimi'] in ['TRY', 'TL']
                                        if not is_try: is_doviz_match = abs(real_fark_doviz) < 0.1
                                    
                                    if is_tl_match and is_doviz_match: durum = "✅ Tam Eşleşme"
                                    elif is_tl_match: durum = "⚠️ Kur Farkı"
                                    else: durum = "❌ Tutar Farkı"
                                    eslesenler.append(make_row(durum, best_candidate, real_fark_tl, real_fark_doviz))

                        else:
                            # C/H MODU
                            pid = row['Payment_ID']
                            if not match_found and pid and len(pid) > 2:
                                if pid in onlar_dict_pay_id:
                                    candidates = onlar_dict_pay_id[pid]
                                    unused = [c for c in candidates if c['unique_idx'] not in matched_onlar_indices]
                                    best_candidate = None
                                    min_diff = float('inf')
                                    for cand in (unused if unused else candidates):
                                        diff = abs(cand[aranan_yon] - aranan_tutar)
                                        if diff < min_diff: min_diff = diff; best_candidate = cand
                                    
                                    if best_candidate is not None and min_diff < 0.1:
                                        match_found = True
                                        matched_onlar_indices.add(best_candidate['unique_idx'])
                                        eslesen_odemeler.append(make_row("✅ Referans Eşleşmesi", best_candidate, 0.0))

                            mid = row['Match_ID']
                            if not match_found and mid and mid in onlar_dict_id:
                                candidates = onlar_dict_id[mid]
                                unused = [c for c in candidates if c['unique_idx'] not in matched_onlar_indices]
                                pool = unused if unused else candidates
                                best_candidate = None
                                min_diff_abs = float('inf')
                                filtered = [c for c in pool if c['Para_Birimi'] == row['Para_Birimi']]
                                search_pool = filtered if filtered else pool
                                for cand in search_pool:
                                    diff = abs(cand[aranan_yon] - aranan_tutar)
                                    if diff < min_diff_abs: min_diff_abs = diff; best_candidate = cand
                                
                                if best_candidate is not None:
                                    match_found = True
                                    matched_onlar_indices.add(best_candidate['unique_idx'])
                                    real_fark_tl = aranan_tutar - best_candidate[aranan_yon]
                                    real_fark_doviz = 0
                                    durum = ""
                                    is_tl_match = min_diff_abs < 0.1
                                    is_doviz_match = True
                                    is_try = row['Para_Birimi'] in ['TRY', 'TL']
                                    if doviz_raporda:
                                        real_fark_doviz = row['Doviz_Tutari'] - best_candidate['Doviz_Tutari']
                                        if not is_try: is_doviz_match = abs(real_fark_doviz) < 0.1
                                    
                                    if is_tl_match and is_doviz_match: durum = "✅ Tam Eşleşme"
                                    elif is_tl_match: durum = "⚠️ Kur Farkı"
                                    else: durum = "❌ Tutar Farkı"
                                    eslesenler.append(make_row(durum, best_candidate, real_fark_tl, real_fark_doviz))

                            if not match_found:
                                key = f"{round(aranan_tutar, 2)}_{row['Para_Birimi']}"
                                if key in onlar_dict_tutar:
                                    candidates = onlar_dict_tutar[key]
                                    unused = [c for c in candidates if c['unique_idx'] not in matched_onlar_indices]
                                    best_match = None
                                    for cand in (unused if unused else candidates):
                                        if pd.notna(row['Tarih_Odeme']) and pd.notna(cand['Tarih_Odeme']):
                                            days_diff = abs((row['Tarih_Odeme'] - cand['Tarih_Odeme']).days)
                                            if days_diff <= 3: best_match = cand; break
                                    if best_match is not None:
                                        matched_onlar_indices.add(best_match['unique_idx'])
                                        eslesen_odemeler.append(make_row("✅ Ödeme/Tarih Eşleşmesi", best_match, 0.0, 0.0))
                                        match_found = True
                        
                        if not match_found:
                            data_unmatched = {
                                "Durum": "🔴 Bizde Var / Onlarda Yok",
                                "Belge No": row['Orijinal_Belge_No'],
                                "Tarih": safe_strftime(row['Tarih']),
                                "Tutar": aranan_tutar,
                                "Döviz Tutar": row['Doviz_Tutari'] if doviz_raporda else 0
                            }
                            for c in extra_cols_biz: data_unmatched[f"BİZ: {c}"] = str(row.get(c, ""))
                            unmatched_biz.append(data_unmatched)

                unmatched_onlar = []
                for idx, row in clean_onlar.iterrows():
                    if row['unique_idx'] not in matched_onlar_indices:
                        tutar = row['Borc'] if row['Borc'] > 0 else row['Alacak']
                        data_un = {
                            "Durum": "🔵 Onlarda Var / Bizde Yok",
                            "Belge No": row['Orijinal_Belge_No'],
                            "Tarih": safe_strftime(row['Tarih']),
                            "Tutar": tutar,
                            "Döviz Tutar": row['Doviz_Tutari'] if doviz_raporda else 0
                        }
                        for c in extra_cols_onlar: data_un[f"KARŞI: {c}"] = str(row.get(c, ""))
                        unmatched_onlar.append(data_un)

            st.session_state.sonuclar = {
                "ozet": df_ozet_rapor,
                "eslesen": pd.DataFrame(eslesenler),
                "odeme": pd.DataFrame(eslesen_odemeler),
                "un_biz": pd.DataFrame(unmatched_biz),
                "un_onlar": pd.DataFrame(unmatched_onlar)
            }
            st.session_state.analiz_yapildi = True
            st.success(f"Analiz Tamamlandı! Süre: {time.time() - start_time:.2f} saniye.")

        except Exception as e:
            st.error(f"Hata: {e}")

# --- SONUC GÖSTERME KISMI (GÜVENLİ) ---
if st.session_state.get('analiz_yapildi', False):
    res = st.session_state.sonuclar
    
    total_recs = len(res["eslesen"]) + len(res["odeme"]) + len(res["un_biz"]) + len(res["un_onlar"])
    
    if total_recs > 0:
        match_rate = ((len(res["eslesen"]) + len(res["odeme"])) / total_recs) * 100
        miss_rate = ((len(res["un_biz"]) + len(res["un_onlar"])) / total_recs) * 100
        
        st.markdown("### 📊 Durum Özeti")
        k1, k2, k3 = st.columns(3)
        k1.metric("✅ Eşleşme Oranı", f"%{match_rate:.1f}")
        k2.metric("❌ Fark/Eksik Oranı", f"%{miss_rate:.1f}")
        k3.metric("📄 Toplam Kayıt", f"{total_recs} Adet")
        st.divider()

    df_hatali = pd.DataFrame()
    if not res["eslesen"].empty:
        df_hatali = res["eslesen"][res["eslesen"]['Durum'].str.contains('❌|⚠️', na=False)]
    
    df_eslesen_temiz = res["eslesen"]
    if not res["eslesen"].empty:
        df_eslesen_temiz = res["eslesen"][~res["eslesen"]['Durum'].str.contains('❌|⚠️', na=False)]

    dfs_to_export = {
        "ÖZET_BAKIYE": res["ozet"],
        "Eşleşen Faturalar": df_eslesen_temiz,
        "Eşleşen Ödemeler": res["odeme"],
        "Hatalı Eşleşmeler": df_hatali,
        "Bizde Var - Yok": res["un_biz"],
        "Onlarda Var - Yok": res["un_onlar"]
    }
    
    c_down1, c_down2 = st.columns(2)
    with c_down1:
        st.download_button("📥 Excel İndir (Ayrı Sayfalar)", excel_indir_coklu(dfs_to_export), "Mutabakat_Split.xlsx")
    with c_down2:
        st.download_button("📥 Excel İndir (Tek Liste/Özet)", excel_indir_tek_sayfa(dfs_to_export), "Mutabakat_Tek_Liste.xlsx", type="primary")

    tabs_list = ["📈 Özet", "✅ Faturalar", "⚠️ Hatalılar", "🔴 Bizde Var / Yok", "🔵 Onlarda Var / Yok"]
    if not is_insurance: tabs_list.insert(2, "💰 Ödemeler")
    
    tabs = st.tabs(tabs_list)
    
    with tabs[0]:
        st.dataframe(res["ozet"].style.format(precision=2), use_container_width=True)
    with tabs[1]:
        if not df_eslesen_temiz.empty:
            st.dataframe(df_eslesen_temiz.style.map(lambda v: 'color: green', subset=['Durum']), use_container_width=True)
        else: st.info("Fatura eşleşmesi yok.")
    
    if not is_insurance:
        with tabs[2]:
            if not res["odeme"].empty:
                st.dataframe(res["odeme"].style.map(lambda v: 'color: blue', subset=['Durum']), use_container_width=True)
            else: st.info("Ödeme eşleşmesi yok.")
        idx_offset = 1
    else: idx_offset = 0
        
    with tabs[2+idx_offset]:
        if not df_hatali.empty:
            st.dataframe(df_hatali.style.map(lambda v: 'color: red', subset=['Durum']), use_container_width=True)
        else: st.success("Hatalı kayıt yok.")
    with tabs[3+idx_offset]:
        st.dataframe(res["un_biz"], use_container_width=True)
    with tabs[4+idx_offset]:
        st.dataframe(res["un_onlar"], use_container_width=True)

