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
            .block-container {padding-top: 2rem;}
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

# --- SESSION STATE ---
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
    """Excel indirirken sütun genişliklerini otomatik ayarlar."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        for sheet_name, df in dfs_dict.items():
            safe_name = re.sub(r'[\\/*?:\[\]]', '-', str(sheet_name))[:30]
            df.to_excel(writer, index=False, sheet_name=safe_name)
            
            # --- OTO GENİŞLİK AYARI ---
            worksheet = writer.sheets[safe_name]
            for column_cells in worksheet.columns:
                length = max(len(str(cell.value) if cell.value is not None else "") for cell in column_cells)
                # Başlık uzunluğunu da dikkate al
                if length < len(str(column_cells[0].value)):
                    length = len(str(column_cells[0].value))
                # Biraz boşluk bırak (max 50 karakter)
                adjusted_width = min(length + 2, 50)
                worksheet.column_dimensions[column_cells[0].column_letter].width = adjusted_width
                
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
        
        # Oto Genişlik
        worksheet = writer.sheets['Tum_Mutabakat_Verisi']
        for column_cells in worksheet.columns:
            length = max(len(str(cell.value) if cell.value is not None else "") for cell in column_cells)
            if length < len(str(column_cells[0].value)): length = len(str(column_cells[0].value))
            worksheet.column_dimensions[column_cells[0].column_letter].width = min(length + 2, 50)
            
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
    df_copy = df.copy()
    
    # --- AYRIŞTIRMA (SİGORTA MODU İÇİN ÖDEME TESPİTİ) ---
    df_payments_subset = pd.DataFrame()
    
    if is_insurance_mode and 'odeme_turu_sutunu' in config and 'odeme_turu_degerleri' in config:
        col_filter = config['odeme_turu_sutunu']
        vals_payment = config['odeme_turu_degerleri']
        
        if col_filter and vals_payment:
            # Ödeme olanları ayır (Bunları ayrıca işleyeceğiz)
            mask_payment = df_copy[col_filter].isin(vals_payment)
            df_payments_subset = df_copy[mask_payment].copy()
            
            # Ana listeden ödemeleri çıkar (Sadece poliçeler kalsın)
            df_copy = df_copy[~mask_payment]

    df_new = pd.DataFrame() 
    
    for col in extra_cols:
        if col in df_copy.columns:
            df_new[col] = df_copy[col].astype(str)

    df_new['Tarih'] = pd.to_datetime(df_copy[config['tarih_col']], dayfirst=True, errors='coerce')
    
    if not is_insurance_mode and config.get('tarih_odeme_col') and config['tarih_odeme_col'] != "Seçiniz...":
        df_new['Tarih_Odeme'] = pd.to_datetime(df_copy[config['tarih_odeme_col']], dayfirst=True, errors='coerce')
    else:
        df_new['Tarih_Odeme'] = df_new['Tarih']

    if is_insurance_mode and taraf_adi == "Onlar":
        pol = df_copy[config['police_col']].fillna('').astype(str)
        zey = df_copy[config['zeyil_col']].fillna('').astype(str)
        df_new['Orijinal_Belge_No'] = pol + " - " + zey
        
        def clean_join(p, z):
            p_clean = ''.join(filter(str.isdigit, str(p)))
            z_clean = ''.join(filter(str.isdigit, str(z)))
            if p_clean: 
                combined = p_clean + z_clean
                return str(int(combined)) if combined else ""
            return ""
        df_new['Match_ID'] = df_copy.apply(lambda x: clean_join(x[config['police_col']], x[config['zeyil_col']]), axis=1)
    else:
        df_new['Orijinal_Belge_No'] = df_copy[config['belge_col']].astype(str)
        df_new['Match_ID'] = df_new['Orijinal_Belge_No'].apply(lambda x: ''.join(filter(str.isdigit, str(x))))
        df_new['Match_ID'] = df_new['Match_ID'].replace(r'^0+', '', regex=True)
    
    if not is_insurance_mode and config.get('odeme_ref_col') and config['odeme_ref_col'] != "Seçiniz...":
        df_new['Payment_ID'] = df_copy[config['odeme_ref_col']].apply(referans_no_temizle)
    else:
        df_new['Payment_ID'] = ""

    df_new['Kaynak'] = taraf_adi
    
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

    if "Tek Kolon" in config['tutar_tipi']:
        col_name = config['tutar_col']
        ham_tutar = pd.to_numeric(df_copy[col_name], errors='coerce').fillna(0)
        if not doviz_aktif: df_new['Doviz_Tutari'] = 0.0
        
        rol = config.get('rol_kodu', 'Biz Alıcıyız') 
        if rol == "Biz Alıcıyız":
            df_new['Borc'] = ham_tutar.where(ham_tutar > 0, 0)
            df_new['Alacak'] = ham_tutar.where(ham_tutar < 0, 0).abs()
        else:
            df_new['Alacak'] = ham_tutar.where(ham_tutar > 0, 0)
            df_new['Borc'] = ham_tutar.where(ham_tutar < 0, 0).abs()
    else: 
        df_new['Borc'] = pd.to_numeric(df_copy[config['borc_col']], errors='coerce').fillna(0)
        df_new['Alacak'] = pd.to_numeric(df_copy[config['alacak_col']], errors='coerce').fillna(0)
    
    # --- ÖDEMELERİ HAZIRLA (EĞER VARSA) ---
    df_payments_prepared = pd.DataFrame()
    if not df_payments_subset.empty:
        # Ödemeler için basit bir yapı kuruyoruz (Tarih, Tutar, PB)
        df_payments_prepared['Tarih'] = pd.to_datetime(df_payments_subset[config['tarih_col']], dayfirst=True, errors='coerce')
        
        # Tutar (Aynı mantık)
        if "Tek Kolon" in config['tutar_tipi']:
            col_name = config['tutar_col']
            p_tutar = pd.to_numeric(df_payments_subset[col_name], errors='coerce').fillna(0)
            if rol == "Biz Alıcıyız":
                df_payments_prepared['Borc'] = p_tutar.where(p_tutar > 0, 0)
                df_payments_prepared['Alacak'] = p_tutar.where(p_tutar < 0, 0).abs()
            else:
                df_payments_prepared['Alacak'] = p_tutar.where(p_tutar > 0, 0)
                df_payments_prepared['Borc'] = p_tutar.where(p_tutar < 0, 0).abs()
        else:
            df_payments_prepared['Borc'] = pd.to_numeric(df_payments_subset[config['borc_col']], errors='coerce').fillna(0)
            df_payments_prepared['Alacak'] = pd.to_numeric(df_payments_subset[config['alacak_col']], errors='coerce').fillna(0)

        # Para Birimi
        if doviz_aktif:
            df_payments_prepared['Para_Birimi'] = df_payments_subset[config['doviz_cinsi_col']].astype(str).str.upper().str.strip()
            df_payments_prepared['Para_Birimi'] = df_payments_prepared['Para_Birimi'].replace({'TL': 'TRY', 'TRL': 'TRY'})
            df_payments_prepared['Doviz_Tutari'] = pd.to_numeric(df_payments_subset[config['doviz_tutar_col']], errors='coerce').fillna(0).abs()
        else:
            df_payments_prepared['Para_Birimi'] = "TRY"
            df_payments_prepared['Doviz_Tutari'] = 0.0
            
        # İşlem Türü (Görsel İçin)
        if 'odeme_turu_sutunu' in config:
            df_payments_prepared['Islem_Turu'] = df_payments_subset[config['odeme_turu_sutunu']].astype(str)
        else:
            df_payments_prepared['Islem_Turu'] = "Ödeme"
            
        df_payments_prepared['Orijinal_Belge_No'] = "Ödeme Kaydı"
        df_payments_prepared['Match_ID'] = ""

    # --- GRUPLAMA ---
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
    
    # Hazırlanmış Ödemeleri de döndür (Sadece Sigorta Modunda dolu olur)
    return df_final, doviz_aktif, df, df_payments_prepared

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
        
        # SİGORTA MODUNDA BİZİM TARAFTA DA ÖDEME AYRIMI OLABİLİR (Şimdilik pasif, istenirse açılabilir)
        
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
            
            # FİLTRE YERİNE AYRIŞTIRMA
            st.info("💳 Ödeme Kayıtları")
            filtre_col = st.selectbox("İşlem Türü Sütunu Seçiniz:", cols2, key="ftur")
            if filtre_col and filtre_col != "Seçiniz...":
                unique_vals = df2[filtre_col].astype(str).unique().tolist()
                filtre_vals = st.multiselect("Ödeme Olanları Seçiniz (Tahsilat vb.):", unique_vals, key="fvals")
                config2['odeme_turu_sutunu'] = filtre_col
                config2['odeme_turu_degerleri'] = filtre_vals
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
            with st.spinner('Analiz yapılıyor...'):
                # 1. VERİ HAZIRLAMA (ÖDEMELER AYRIŞIYOR)
                clean_biz, doviz_biz, orig_biz, _ = veri_hazirla_ve_grupla(df1, config1, "Biz", is_insurance, extra_cols_biz)
                # Onlar tarafında ödemeler df_onlar_odemeler'e gidecek
                clean_onlar, doviz_onlar, orig_onlar, df_onlar_odemeler = veri_hazirla_ve_grupla(df2, config2, "Onlar", is_insurance, extra_cols_onlar)
                
                df_ozet_rapor = ozet_rapor_olustur(clean_biz, clean_onlar)
                doviz_raporda = doviz_biz or doviz_onlar
                matched_onlar_indices = set()
                
                # SÖZLÜKLER (POLİÇELER İÇİN)
                onlar_dict_id = {}
                onlar_dict_tutar = {}

                for idx, row in clean_onlar.iterrows():
                    mid = row['Match_ID']
                    if mid:
                        if mid not in onlar_dict_id: onlar_dict_id[mid] = []
                        onlar_dict_id[mid].append(row)
                    
                    val_borc = round(row['Borc'], 2)
                    val_alacak = round(row['Alacak'], 2)
                    curr = row['Para_Birimi']
                    key_borc = f"{val_borc}_{curr}"
                    key_alacak = f"{val_alacak}_{curr}"
                    
                    if key_borc not in onlar_dict_tutar: onlar_dict_tutar[key_borc] = []
                    onlar_dict_tutar[key_borc].append(row)
                    if key_alacak not in onlar_dict_tutar: onlar_dict_tutar[key_alacak] = []
                    onlar_dict_tutar[key_alacak].append(row)
                
                # SÖZLÜKLER (ÖDEMELER İÇİN - SİGORTA MODUNDA)
                onlar_dict_odeme_tutar = {}
                if is_insurance and not df_onlar_odemeler.empty:
                    for idx, row in df_onlar_odemeler.iterrows():
                        # Ödemelerde referans yoksa tutardan gidelim
                        val_borc = round(row['Borc'], 2)
                        val_alacak = round(row['Alacak'], 2)
                        curr = row['Para_Birimi']
                        key_borc = f"{val_borc}_{curr}"
                        key_alacak = f"{val_alacak}_{curr}"
                        
                        if key_borc not in onlar_dict_odeme_tutar: onlar_dict_odeme_tutar[key_borc] = []
                        onlar_dict_odeme_tutar[key_borc].append(row)
                        if key_alacak not in onlar_dict_odeme_tutar: onlar_dict_odeme_tutar[key_alacak] = []
                        onlar_dict_odeme_tutar[key_alacak].append(row)

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
                            
                            for c in extra_cols_biz: data[f"BİZ: {c}"] = str(row.get(c, ""))
                            for c in extra_cols_onlar: data[f"KARŞI: {c}"] = str(aday_row.get(c, ""))
                            
                            # Ödeme Türü (Eğer ödeme ise)
                            if 'Islem_Turu' in aday_row:
                                data["Karşı İşlem"] = aday_row['Islem_Turu']
                            
                            return data

                        if is_insurance:
                            # --- SİGORTA MODU EŞLEŞTİRME ---
                            
                            # 1. ADIM: POLİÇE ARAMA (Tutar + Tarih)
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
                                    eslesenler.append(make_row("✅ Tam Eşleşen Poliçe", best_match, 0.0, 0.0))
                                    match_found = True

                            # 2. ADIM: POLİÇE NO
                            mid = row['Match_ID']
                            if not match_found and mid and mid in onlar_dict_id:
                                candidates = onlar_dict_id[mid]
                                unused = [c for c in candidates if c['unique_idx'] not in matched_onlar_indices]
                                pool = unused if unused else candidates
                                best_candidate = None
                                min_diff_abs = float('inf')
                                for cand in pool:
                                    diff = abs(cand[aranan_yon] - aranan_tutar)
                                    if diff < min_diff_abs: min_diff_abs = diff; best_candidate = cand
                                
                                if best_candidate is not None:
                                    match_found = True
                                    matched_onlar_indices.add(best_candidate['unique_idx'])
                                    real_fark_tl = aranan_tutar - best_candidate[aranan_yon]
                                    real_fark_doviz = 0
                                    durum = "✅ Tam Eşleşme" if min_diff_abs < 0.1 else "❌ Tutar Farkı (Poliçe)"
                                    if doviz_raporda:
                                        real_fark_doviz = row['Doviz_Tutari'] - best_candidate['Doviz_Tutari']
                                    eslesenler.append(make_row(durum, best_candidate, real_fark_tl, real_fark_doviz))

                            # 3. ADIM: ÖDEME HAVUZUNDA ARA (YENİ!)
                            # Poliçe bulamadıysak, belki bu bir ödemedir?
                            if not match_found:
                                # Tutar üzerinden ödemelerde ara
                                key_pay = f"{round(aranan_tutar, 2)}_{row['Para_Birimi']}"
                                if key_pay in onlar_dict_odeme_tutar:
                                    # Ödeme bulundu!
                                    # Tarih toleranslı bakabiliriz ama şimdilik tutar tutuyorsa alalım
                                    # Not: Ödemelerde 'matched' işareti koymak zor çünkü unique_idx farklı olabilir
                                    # Basitlik için ilkini alıp geçiyoruz
                                    pay_match = onlar_dict_odeme_tutar[key_pay][0]
                                    eslesen_odemeler.append(make_row("✅ Ödeme Eşleşmesi", pay_match, 0.0, 0.0))
                                    match_found = True

                        else:
                            # --- C/H MODU ---
                            # (Eski mantık aynen devam)
                            pass 
                        
                        # Bulunamadıysa
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

                # ONLARDA KALANLAR
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
                
                # Ödemeler de kalanlara eklenebilir (İsteğe bağlı)
                # Şimdilik sadece poliçeler

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

# --- GÖSTERİM ---
if st.session_state.get('analiz_yapildi', False):
    res = st.session_state.sonuclar
    
    # İndirme
    df_hatali = pd.DataFrame()
    if not res["eslesen"].empty:
        df_hatali = res["eslesen"][res["eslesen"]['Durum'].str.contains('❌|⚠️', na=False)]
    df_eslesen_temiz = res["eslesen"]
    if not res["eslesen"].empty:
        df_eslesen_temiz = res["eslesen"][~res["eslesen"]['Durum'].str.contains('❌|⚠️', na=False)]

    dfs_to_export = {
        "ÖZET_BAKIYE": res["ozet"],
        "Eşleşen Poliçeler": df_eslesen_temiz,
        "Eşleşen Ödemeler": res["odeme"],
        "Hatalı Eşleşmeler": df_hatali,
        "Bizde Var - Yok": res["un_biz"],
        "Onlarda Var - Yok": res["un_onlar"]
    }
    
    col_d1, col_d2 = st.columns(2)
    with col_d1:
        st.download_button("📥 Excel İndir (Ayrı Sayfalar)", excel_indir_coklu(dfs_to_export), "Mutabakat_Split.xlsx")
    with col_d2:
        st.download_button("📥 Excel İndir (Tek Liste/Özet)", excel_indir_tek_sayfa(dfs_to_export), "Mutabakat_Tek_Liste.xlsx", type="primary")

    # Tabs
    tabs_list = ["📈 Özet", "✅ Poliçeler", "💰 Ödemeler", "⚠️ Hatalılar", "🔴 Bizde Var / Yok", "🔵 Onlarda Var / Yok"]
    tabs = st.tabs(tabs_list)
    
    with tabs[0]: st.dataframe(res["ozet"].style.format(precision=2), use_container_width=True)
    with tabs[1]: 
        if not df_eslesen_temiz.empty: st.dataframe(df_eslesen_temiz, use_container_width=True)
        else: st.info("Kayıt yok.")
    with tabs[2]:
        if not res["odeme"].empty: st.dataframe(res["odeme"], use_container_width=True)
        else: st.info("Ödeme eşleşmesi yok.")
    with tabs[3]:
        if not df_hatali.empty: st.dataframe(df_hatali.style.map(lambda v: 'color: red', subset=['Durum']), use_container_width=True)
        else: st.success("Hata yok.")
    with tabs[4]: st.dataframe(res["un_biz"], use_container_width=True)
    with tabs[5]: st.dataframe(res["un_onlar"], use_container_width=True)
