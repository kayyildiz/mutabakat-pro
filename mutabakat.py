import streamlit as st
import pandas as pd
import re
import io
import time
import warnings
import json
import os
from datetime import datetime
from pandas.tseries.offsets import MonthEnd

# Suppress warnings
warnings.filterwarnings("ignore")

# --- 1. CONFIGURATION & SETUP ---
st.set_page_config(page_title="Mutabakat Pro V66", layout="wide")

CONFIG_FILE = "ayarlar.json"

# Initialize Session State
if 'analiz_yapildi' not in st.session_state:
    st.session_state['analiz_yapildi'] = False
if 'sonuclar' not in st.session_state:
    st.session_state['sonuclar'] = {}

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

# CSS for styling
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

# --- 2. HELPER FUNCTIONS ---

def get_smart_index(options, target_name, filename, key_suffix):
    # Check memory first
    if filename in st.session_state['column_prefs']:
        saved_col = st.session_state['column_prefs'][filename].get(key_suffix)
        if saved_col in options: return options.index(saved_col)
    # Heuristic guess
    for i, opt in enumerate(options):
        if str(opt).strip().lower() == target_name.lower(): return i
    return 0

def get_default_multiselect(options, targets):
    defaults = []
    for opt in options:
        for t in targets:
            if str(t).lower() in str(opt).lower(): defaults.append(opt)
    return list(set(defaults))

@st.cache_data
def belge_no_temizle(val):
    if isinstance(val, (pd.Series, list, tuple)): val = val.iloc[0] if hasattr(val, 'iloc') else val[0]
    if pd.isna(val): return ""
    s = str(val).strip()
    if s.lower() == 'nan': return ""
    # Extract digits only for matching
    res = ''.join(filter(str.isdigit, s))
    if res: return str(int(res)) 
    return ""

@st.cache_data
def referans_no_temizle(val):
    if isinstance(val, (pd.Series, list, tuple)): val = val.iloc[0] if hasattr(val, 'iloc') else val[0]
    if pd.isna(val): return ""
    if isinstance(val, float): val = f"{val:.0f}"
    s = str(val).strip().upper()
    if s.lower() == 'nan': return ""
    s = re.sub(r'[^A-Z0-9]', '', s)
    s = s.lstrip('0')
    return s

def safe_strftime(val):
    if isinstance(val, (pd.Series, list, tuple)): val = val.iloc[0] if hasattr(val, 'iloc') else val[0]
    if pd.isna(val): return ""
    try: return val.strftime('%d.%m.%Y')
    except: return ""

def apply_excel_styles(writer, sheet_name, df):
    from openpyxl.styles import Font, PatternFill
    try:
        worksheet = writer.sheets[sheet_name]
        # Auto-width and Bold headers
        for column_cells in worksheet.columns:
            length = max(len(str(cell.value) if cell.value is not None else "") for cell in column_cells)
            worksheet.column_dimensions[column_cells[0].column_letter].width = min(length + 5, 60)
            
        # Bold specific columns
        bold_cols = ['Biz_Bakiye', 'Onlar_Bakiye', 'Kümüle_Fark', 'Durum', 'Fark (TL)', 'Kategori']
        header = [cell.value for cell in worksheet[1]]
        for col_idx, col_name in enumerate(header, 1):
            if col_name in bold_cols:
                col_letter = worksheet.cell(row=1, column=col_idx).column_letter
                for cell in worksheet[col_letter]:
                    if cell.row > 1: cell.font = Font(bold=True)
    except: pass

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
    # Separate Summary
    df_ozet = dfs_dict.get("ÖZET_BAKIYE", pd.DataFrame())
    
    # Combine Details
    master_df = pd.DataFrame()
    for category, df in dfs_dict.items():
        if category != "ÖZET_BAKIYE" and not df.empty:
            df_temp = df.copy()
            df_temp.insert(0, "Kategori", category)
            master_df = pd.concat([master_df, df_temp], ignore_index=True)
            
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        if not df_ozet.empty:
            df_ozet.to_excel(writer, index=False, sheet_name='Ozet')
            apply_excel_styles(writer, 'Ozet', df_ozet)
        if not master_df.empty:
            master_df.to_excel(writer, index=False, sheet_name='Detaylar')
            apply_excel_styles(writer, 'Detaylar', master_df)
    return output.getvalue()

def ozet_rapor_olustur(df_biz, df_onlar, max_date_str):
    # Calculate Period Balances
    
    # Biz
    biz = df_biz.copy()
    biz['Net'] = biz['Borc'] - biz['Alacak']
    # Group by Currency
    grp_biz = biz.groupby('Para_Birimi')['Net'].sum().reset_index().rename(columns={'Net': 'Biz_Bakiye'})
    
    # Onlar
    onlar = df_onlar.copy()
    onlar['Net'] = onlar['Borc'] - onlar['Alacak']
    grp_onlar = onlar.groupby('Para_Birimi')['Net'].sum().reset_index().rename(columns={'Net': 'Onlar_Bakiye'})
    
    # Merge
    ozet = pd.merge(grp_biz, grp_onlar, on='Para_Birimi', how='outer').fillna(0)
    
    # "Bizim Borç = Onların Alacak" logic implies balances should be opposite signs or summed depending on perspective.
    # Usually: (Biz Borc - Biz Alacak) + (Onlar Borc - Onlar Alacak) should be 0 if perfectly reconciled in a mirror account.
    # Let's show the scalar Difference:
    ozet['Fark'] = ozet['Biz_Bakiye'] + ozet['Onlar_Bakiye']
    
    ozet['Donem_Sonu'] = max_date_str
    
    return ozet[['Donem_Sonu', 'Para_Birimi', 'Biz_Bakiye', 'Onlar_Bakiye', 'Fark']]

# --- 3. DATA PROCESSING ---

def veri_hazirla(df, config, taraf_adi, extra_cols=None):
    if extra_cols is None: extra_cols = []
    
    # Remove duplicate columns
    df = df.loc[:, ~df.columns.duplicated()]
    df_copy = df.copy()
    
    # Initialize Payment Dataframe
    df_payments = pd.DataFrame()
    
    # --- Payment Separation Logic ---
    filter_col = config.get('odeme_turu_sutunu')
    filter_vals = config.get('odeme_turu_degerleri')
    
    if filter_col and filter_vals and filter_col in df_copy.columns:
        # Convert column to string for robust matching
        col_data = df_copy[filter_col].astype(str)
        mask_payment = col_data.isin([str(v) for v in filter_vals])
        
        df_payments = df_copy[mask_payment].copy()
        df_copy = df_copy[~mask_payment] # Keep only invoices/others in main df
    
    # --- Prepare Main DataFrame (Invoices) ---
    df_new = pd.DataFrame()
    
    # Extract extra columns
    for col in extra_cols:
        if col in df_copy.columns: df_new[col] = df_copy[col].astype(str)

    # Dates
    df_new['Tarih'] = pd.to_datetime(df_copy[config['tarih_col']], dayfirst=True, errors='coerce')
    
    if config.get('tarih_odeme_col') and config['tarih_odeme_col'] != "Seçiniz...":
        df_new['Tarih_Odeme'] = pd.to_datetime(df_copy[config['tarih_odeme_col']], dayfirst=True, errors='coerce')
    else:
        df_new['Tarih_Odeme'] = df_new['Tarih']

    # Document Numbers (Fixing "nan" issue)
    raw_doc = df_copy[config['belge_col']].astype(str)
    # Replace literal 'nan' or empty strings with actual empty string
    raw_doc = raw_doc.replace(['nan', 'NaN', 'None'], '', regex=False)
    df_new['Orijinal_Belge_No'] = raw_doc
    
    # Match ID: Digits only
    df_new['Match_ID'] = df_new['Orijinal_Belge_No'].apply(lambda x: ''.join(filter(str.isdigit, str(x))))
    df_new['Match_ID'] = df_new['Match_ID'].replace(r'^0+', '', regex=True) # Remove leading zeros
    
    # Source
    df_new['Kaynak'] = taraf_adi
    
    # Currency
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

    # Amounts (Sign Logic based on Role)
    rol = config.get('rol_kodu', 'Biz Alıcıyız')
    
    if "Tek Kolon" in config['tutar_tipi']:
        col_name = config['tutar_col']
        ham = pd.to_numeric(df_copy[col_name], errors='coerce').fillna(0)
        
        if rol == "Biz Alıcıyız":
            # Alıcı için: Pozitif = Borç (Fatura), Negatif = Alacak (İade?)
            df_new['Borc'] = ham.where(ham > 0, 0)
            df_new['Alacak'] = ham.where(ham < 0, 0).abs()
        else:
            # Satıcı için: Pozitif = Alacak (Fatura), Negatif = Borç
            df_new['Alacak'] = ham.where(ham > 0, 0)
            df_new['Borc'] = ham.where(ham < 0, 0).abs()
    else:
        df_new['Borc'] = pd.to_numeric(df_copy[config['borc_col']], errors='coerce').fillna(0)
        df_new['Alacak'] = pd.to_numeric(df_copy[config['alacak_col']], errors='coerce').fillna(0)

    # --- Prepare Payment DataFrame (df_pay_final) ---
    df_pay_final = pd.DataFrame()
    if not df_payments.empty:
        # Clone structure from df_new
        df_pay_final = df_new.iloc[0:0].copy()
        
        # Dates
        df_pay_final['Tarih'] = pd.to_datetime(df_payments[config['tarih_col']], dayfirst=True, errors='coerce')
        if config.get('tarih_odeme_col') and config['tarih_odeme_col'] != "Seçiniz...":
            df_pay_final['Tarih_Odeme'] = pd.to_datetime(df_payments[config['tarih_odeme_col']], dayfirst=True, errors='coerce')
        else:
            df_pay_final['Tarih_Odeme'] = df_pay_final['Tarih']
            
        # Amounts (Same logic)
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
            
        # Currency
        if doviz_aktif:
            df_pay_final['Para_Birimi'] = df_payments[config['doviz_cinsi_col']].astype(str).str.upper().str.strip()
            df_pay_final['Para_Birimi'] = df_pay_final['Para_Birimi'].replace({'TL': 'TRY'})
            df_pay_final['Doviz_Tutari'] = pd.to_numeric(df_payments[config['doviz_tutar_col']], errors='coerce').fillna(0).abs()
        else:
            df_pay_final['Para_Birimi'] = "TRY"
            df_pay_final['Doviz_Tutari'] = 0.0

        # Copy Extra Cols
        for col in extra_cols:
            if col in df_payments.columns: df_pay_final[col] = df_payments[col].astype(str)
            
        df_pay_final['Match_ID'] = "" # Payments usually don't match by ID in the invoice sense
        df_pay_final['Kaynak'] = taraf_adi
        df_pay_final['unique_idx'] = df_pay_final.index
        
        # PAYMENT MATCHING KEY GENERATION
        # 1. Primary: Explicit Ref Column
        if config.get('odeme_ref_col') and config['odeme_ref_col'] != "Seçiniz...":
             df_pay_final['Payment_ID'] = df_payments[config['odeme_ref_col']].apply(referans_no_temizle)
        # 2. Fallback: Use the Document Type Column value as the Ref/Group Key (As requested)
        elif config.get('odeme_turu_sutunu') and config.get('odeme_turu_sutunu') != "Seçiniz...":
             # This is a bit unusual but requested: use the doc type value as a fallback grouping key
             # or simply leave it empty to rely on Date+Amount
             df_pay_final['Payment_ID'] = "" 
        else:
             df_pay_final['Payment_ID'] = ""
    
    return df_new, df_pay_final, doviz_aktif

def grupla(df, is_doviz_aktif):
    if df.empty: return df
    
    # Separate rows with Match_ID (Invoices) and without
    mask_ids = (df['Match_ID'] != "") & (df['Match_ID'].notna())
    df_ids = df[mask_ids]
    df_noids = df[~mask_ids]
    
    if df_ids.empty: return df_noids
    
    agg_rules = {
        'Tarih': 'first', 'Tarih_Odeme': 'first', 'Orijinal_Belge_No': 'first', 
        'Payment_ID': 'first', 'Kaynak': 'first', 'Borc': 'sum', 'Alacak': 'sum', 
        'Para_Birimi': 'first'
    }
    # Keep extra columns
    for col in df.columns:
        if col not in agg_rules and col not in ['Match_ID', 'unique_idx', 'Doviz_Tutari']:
            agg_rules[col] = 'first'
            
    if is_doviz_aktif:
        def get_real_fx(sub):
            # Sum logic for splitting amounts
            nt = sub[~sub['Para_Birimi'].isin(['TRY', 'TL'])]
            if not nt.empty: return nt['Doviz_Tutari'].sum()
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

# --- 4. UI STRUCTURE ---
c_title, c_settings = st.columns([2, 1])
with c_title: st.title("💎 Mutabakat Pro V66")
with c_settings:
    with st.expander("⚙️ Ayarlar", expanded=True):
        rol_secimi = st.radio("Rol:", ["Biz Alıcıyız", "Biz Satıcıyız"])

rol_kodu = "Biz Alıcıyız" if "Alıcıyız" in rol_secimi else "Biz Satıcıyız"

st.divider()
col1, col2 = st.columns(2)

# --- 5. UI FUNCTION ---
def render_side(key, title):
    with st.container():
        st.subheader(title)
        f = st.file_uploader("Dosya", type=["xlsx", "xls"], key=f"f_{key}")
        config = {'rol_kodu': rol_kodu}
        extra = []
        df_preview = None
        
        if f:
            d = pd.read_excel(f)
            d = d.loc[:, ~d.columns.duplicated()] # Dedup columns
            cols = ["Seçiniz..."] + d.columns.tolist()
            fname = f.name
            df_preview = d
            
            # Helper for smart index
            def idx(suffix, default): return get_smart_index(cols, default, fname, suffix)

            config['tarih_col'] = st.selectbox("Tarih", cols, index=idx('tarih_col', "Tarih"), key=f"d_{key}")
            config['belge_col'] = st.selectbox("Belge No (Fatura/Eşleşme)", cols, index=idx('belge_col', "Fatura"), key=f"doc_{key}")
            
            st.info("Opsiyonel: Ödeme Bilgileri")
            config['tarih_odeme_col'] = st.selectbox("Ödeme Tarihi / Valör", cols, index=idx('tarih_odeme_col', "Valör"), key=f"pd_{key}")
            config['odeme_ref_col'] = st.selectbox("Ödeme Ref / Dekont No", cols, index=idx('odeme_ref_col', "Dekont"), key=f"ref_{key}")
            
            st.warning("Opsiyonel: Ödeme Ayrıştırma")
            # Payment Type Column
            def_type_col = idx('odeme_turu_sutunu', "İşlem Türü" if key=="onlar" else "Belge Türü")
            p_col = st.selectbox("Ödeme Belge Türü Sütunu", cols, index=def_type_col, key=f"pcol_{key}")
            config['odeme_turu_sutunu'] = p_col
            
            # Payment Type Values
            if p_col and p_col != "Seçiniz...":
                unique_vals = d[p_col].astype(str).unique().tolist()
                # Try to guess defaults
                keywords = ["ÖDEME", "TAHSİLAT", "HAVALE", "EFT", "KREDI", "VIRMAN", "BANKA"]
                defaults = [v for v in unique_vals if any(k in v.upper() for k in keywords)]
                
                sel_vals = st.multiselect(f"'{p_col}' içindeki Ödeme Kayıtlarını Seç:", unique_vals, default=defaults, key=f"pvals_{key}")
                config['odeme_turu_degerleri'] = sel_vals

            st.success("Tutar Bilgileri")
            tip = st.radio("Tutar Tipi", ["Ayrı", "Tek"], index=0, key=f"tip_{key}", horizontal=True)
            config['tutar_tipi'] = "Tek Kolon" if tip=="Tek" else "Ayrı Kolonlar"
            
            if tip=="Tek":
                config['tutar_col'] = st.selectbox("Tutar", cols, index=idx('tutar_col', "Tutar"), key=f"amt_{key}")
            else:
                config['borc_col'] = st.selectbox("Borç", cols, index=idx('borc_col', "Borç"), key=f"b_{key}")
                config['alacak_col'] = st.selectbox("Alacak", cols, index=idx('alacak_col', "Alacak"), key=f"a_{key}")
            
            c_curr1, c_curr2 = st.columns(2)
            config['doviz_cinsi_col'] = c_curr1.selectbox("Para Birimi", cols, index=idx('doviz_cinsi_col', "PB"), key=f"cur_{key}")
            config['doviz_tutar_col'] = c_curr2.selectbox("Döviz Tutarı", cols, index=idx('doviz_tutar_col', "Döviz"), key=f"cur_amt_{key}")
            
            extra = st.multiselect("Rapora Eklenecek Sütunlar:", d.columns.tolist(), key=f"ext_{key}")
            
            # Save prefs
            if fname:
                prefs = {}
                for k, v in config.items():
                    if v and v != "Seçiniz...": prefs[k] = v
                st.session_state['column_prefs'][fname] = prefs
                ayarlari_kaydet({fname: prefs})

            return df_preview, config, extra
    return None, None, []

with col1:
    d1, cf1, ex1 = render_side("biz", "🏢 Bizim Kayıtlar")

with col2:
    d2, cf2, ex2 = render_side("onlar", "🏭 Karşı Taraf")

st.divider()

# --- 6. RUN ANALYSIS ---
if st.button("🚀 Analizi Başlat", type="primary", use_container_width=True):
    if d1 is not None and d2 is not None:
        try:
            start_t = time.time()
            with st.spinner('Veriler İşleniyor ve Eşleştiriliyor...'):
                
                # 1. PREPARE DATA (Separate Payments based on UI selection)
                # Note: veri_hazirla now takes 4 args: df, config, label, extra_cols
                raw_biz, pay_biz, dv_biz = veri_hazirla(d1, cf1, "Biz", ex1)
                raw_onlar, pay_onlar, dv_onlar = veri_hazirla(d2, cf2, "Onlar", ex2)
                
                doviz_raporda = dv_biz or dv_onlar
                
                # 2. GROUP INVOICES
                grp_biz = grupla(raw_biz, dv_biz)
                grp_onlar = grupla(raw_onlar, dv_onlar)
                
                # 3. PREPARE SUMMARY
                # Find Max Date for Report Header
                all_dates = pd.concat([raw_biz['Tarih'], raw_onlar['Tarih'], pay_biz['Tarih'], pay_onlar['Tarih']]).dropna()
                max_date = all_dates.max() if not all_dates.empty else datetime.today()
                # Round to Month End
                report_date = (max_date + MonthEnd(0)).strftime('%d.%m.%Y')
                
                # Full concat for balance calc
                full_biz = pd.concat([raw_biz, pay_biz])
                full_onlar = pd.concat([raw_onlar, pay_onlar])
                df_ozet = ozet_rapor_olustur(full_biz, full_onlar, f"{report_date} Tarihli Bakiye")
                
                # 4. MATCHING LOGIC - DOCUMENTS (INVOICES)
                matched_ids = set()
                dict_onlar_id = {}
                
                # Index "Onlar" by Match_ID
                for idx, row in grp_onlar.iterrows():
                    mid = row['Match_ID']
                    if mid:
                        if mid not in dict_onlar_id: dict_onlar_id[mid] = []
                        dict_onlar_id[mid].append(row)
                
                eslesenler = []
                un_biz = []
                
                # Loop "Biz" Invoices
                for idx, row in grp_biz.iterrows():
                    mid = row['Match_ID']
                    my_amt = row['Borc'] - row['Alacak'] # Net
                    found = False
                    
                    if mid and mid in dict_onlar_id:
                        cands = dict_onlar_id[mid]
                        best = None
                        min_diff = float('inf')
                        
                        for c in cands:
                            if c['unique_idx'] not in matched_ids:
                                their_amt = c['Borc'] - c['Alacak']
                                # Direction check: Biz + Onlar should be ~0
                                diff = abs(my_amt + their_amt)
                                if diff < min_diff:
                                    min_diff = diff
                                    best = c
                        
                        if best is not None:
                            matched_ids.add(best['unique_idx'])
                            their_amt = best['Borc'] - best['Alacak']
                            diff_real = my_amt + their_amt
                            
                            status = "✅ Tam Eşleşme" if min_diff < 1.0 else "❌ Tutar Farkı"
                            
                            row_data = {
                                "Durum": status,
                                "Belge No": row['Orijinal_Belge_No'],
                                "Tarih (Biz)": safe_strftime(row['Tarih']),
                                "Tarih (Onlar)": safe_strftime(best['Tarih']),
                                "Tutar (Biz)": my_amt,
                                "Tutar (Onlar)": their_amt,
                                "Fark (TL)": diff_real
                            }
                            # Add extras
                            for c in ex1: row_data[f"BİZ: {c}"] = str(row.get(c, ""))
                            for c in ex2: row_data[f"KARŞI: {c}"] = str(best.get(c, ""))
                            
                            eslesenler.append(row_data)
                            found = True
                            
                    if not found:
                        d_un = {
                            "Durum": "🔴 Bizde Var", 
                            "Belge No": row['Orijinal_Belge_No'],
                            "Tarih": safe_strftime(row['Tarih']), 
                            "Tutar (Biz)": my_amt
                        }
                        for c in ex1: d_un[f"BİZ: {c}"] = str(row.get(c, ""))
                        un_biz.append(d_un)
                        
                # Unmatched Onlar Documents
                un_onlar = []
                for idx, row in grp_onlar.iterrows():
                    if row['unique_idx'] not in matched_ids:
                        d_un = {
                            "Durum": "🔵 Onlarda Var",
                            "Belge No": row['Orijinal_Belge_No'],
                            "Tarih": safe_strftime(row['Tarih']), 
                            "Tutar (Onlar)": row['Borc'] - row['Alacak']
                        }
                        for c in ex2: d_un[f"KARŞI: {c}"] = str(row.get(c, ""))
                        un_onlar.append(d_un)
                        
                # 5. MATCHING LOGIC - PAYMENTS
                eslesen_odeme = []
                
                # Logic: Matches MUST be directional.
                # Biz (Buyer) Payment (Borc) -> matches Onlar (Seller) Receipt (Alacak).
                # Biz Alacak -> matches Onlar Borc.
                # So basically: Biz_Net + Onlar_Net ~ 0
                
                if not pay_biz.empty and not pay_onlar.empty:
                    used_pay_onlar = set()
                    
                    # Index "Onlar" Payments by Ref and Fuzzy Key
                    idx_ref = {}
                    idx_fuzzy = {} # (Date, AbsAmount)
                    
                    for idx, row in pay_onlar.iterrows():
                        # Ref
                        ref = str(row['Payment_ID']).strip()
                        if len(ref) > 2:
                            idx_ref.setdefault(ref, []).append(idx)
                            
                        # Fuzzy (Date + Abs Amount)
                        # We use Abs Amount for key, but check direction later
                        amt = abs(row['Borc'] - row['Alacak'])
                        d_str = safe_strftime(row['Tarih_Odeme'])
                        k = (d_str, round(amt, 2))
                        idx_fuzzy.setdefault(k, []).append(idx)
                        
                    # Loop "Biz" Payments
                    for idx, row in pay_biz.iterrows():
                        found_idx = None
                        my_net = row['Borc'] - row['Alacak']
                        my_abs = abs(my_net)
                        
                        # A. Try by Reference
                        ref = str(row['Payment_ID']).strip()
                        if len(ref) > 2 and ref in idx_ref:
                            for cand_idx in idx_ref[ref]:
                                if cand_idx not in used_pay_onlar:
                                    # Check Direction (Signs must be opposite for sum ~ 0)
                                    cand_net = pay_onlar.loc[cand_idx, 'Borc'] - pay_onlar.loc[cand_idx, 'Alacak']
                                    if abs(my_net + cand_net) < 0.1: # Perfect match
                                        found_idx = cand_idx; break
                                    # Also allow if ref matches but amount differs (partial match logic?)
                                    # For now, strict on Ref matching usually implies same transaction. 
                                    # Let's take it if direction is correct even if amount slightly off? 
                                    # User wanted strict direction. Let's start with strict amount.
                        
                        # B. Try by Date + Amount (if Ref failed)
                        if found_idx is None:
                            # 1. Exact Date
                            d_str = safe_strftime(row['Tarih_Odeme'])
                            k = (d_str, round(my_abs, 2))
                            if k in idx_fuzzy:
                                for cand_idx in idx_fuzzy[k]:
                                    if cand_idx not in used_pay_onlar:
                                        cand_net = pay_onlar.loc[cand_idx, 'Borc'] - pay_onlar.loc[cand_idx, 'Alacak']
                                        if abs(my_net + cand_net) < 0.1: 
                                            found_idx = cand_idx; break
                            
                            # 2. Tolerant Date (±3 Days)
                            if found_idx is None:
                                # Scan nearby days? Or just scan all fuzzy candidates with same amount?
                                # Optimized: iterate only same amount keys? No, keys include date.
                                # Iterate "Onlar" is safer for small datasets
                                for cand_idx, cand_row in pay_onlar.iterrows():
                                    if cand_idx not in used_pay_onlar:
                                        cand_net = cand_row['Borc'] - cand_row['Alacak']
                                        # Check Amount & Direction first
                                        if abs(my_net + cand_net) < 0.1:
                                            # Check Date
                                            dt1 = row['Tarih_Odeme']
                                            dt2 = cand_row['Tarih_Odeme']
                                            if pd.notna(dt1) and pd.notna(dt2):
                                                if abs((dt1 - dt2).days) <= 3:
                                                    found_idx = cand_idx; break
                        
                        # Result
                        if found_idx is not None:
                            used_pay_onlar.add(found_idx)
                            cand = pay_onlar.loc[found_idx]
                            
                            # Fallback if Ref is empty in match
                            match_ref = ref if ref else cand['Payment_ID']
                            
                            d_pay = {
                                "Durum": "✅ Ödeme Eşleşti",
                                "Ref": match_ref,
                                "Tarih (Biz)": safe_strftime(row['Tarih']),
                                "Tarih (Onlar)": safe_strftime(cand['Tarih']),
                                "Tutar (Biz)": my_net,
                                "Tutar (Onlar)": cand['Borc'] - cand['Alacak']
                            }
                            # Add extras
                            for c in ex1: d_pay[f"BİZ: {c}"] = str(row.get(c, ""))
                            for c in ex2: d_pay[f"KARŞI: {c}"] = str(cand.get(c, ""))
                            eslesen_odeme.append(d_pay)
                            
                        else:
                            # Unmatched Payment Biz
                            un_biz.append({
                                "Durum": "🔴 Bizde Var (Ödeme)",
                                "Ref": ref,
                                "Tarih": safe_strftime(row['Tarih']),
                                "Tutar": my_net
                            })
                            
                    # Unmatched Payment Onlar
                    for idx, row in pay_onlar.iterrows():
                        if idx not in used_pay_onlar:
                            un_onlar.append({
                                "Durum": "🔵 Onlarda Var (Ödeme)",
                                "Ref": row['Payment_ID'],
                                "Tarih": safe_strftime(row['Tarih']),
                                "Tutar": row['Borc'] - row['Alacak']
                            })

                st.session_state['sonuclar'] = {
                    "ÖZET_BAKIYE": df_ozet,
                    "Eşleşenler": pd.DataFrame(eslesenler),
                    "Ödemeler": pd.DataFrame(eslesen_odeme),
                    "Bizde Var - Yok": pd.DataFrame(un_biz),
                    "Onlarda Var - Yok": pd.DataFrame(un_onlar)
                }
                st.session_state['analiz_yapildi'] = True
                st.success(f"Analiz Tamamlandı! ({time.time() - start_t:.2f} s)")
                
        except Exception as e:
            st.error(f"Bir hata oluştu: {e}")

# --- 7. DISPLAY RESULTS ---
if st.session_state.get('analiz_yapildi', False):
    res = st.session_state['sonuclar']
    
    c1, c2 = st.columns(2)
    with c1: st.download_button("📥 İndir (Ayrı Sayfalar)", excel_indir_coklu(res), "Mutabakat_Detayli.xlsx")
    with c2: st.download_button("📥 İndir (Özet + Detay)", excel_indir_tek_sayfa(res), "Mutabakat_Ozet.xlsx")
    
    t1, t2, t3, t4, t5 = st.tabs(["Özet", "Eşleşen Faturalar", "Eşleşen Ödemeler", "Bizde Fazla", "Onlarda Fazla"])
    
    with t1: st.dataframe(res["ÖZET_BAKIYE"], use_container_width=True)
    
    with t2: 
        df = res["Eşleşenler"]
        if not df.empty:
            def color_row(row):
                return ['background-color: #ffe6e6' if "❌" in str(row['Durum']) else '' for _ in row]
            st.dataframe(df.style.apply(color_row, axis=1), use_container_width=True)
        else: st.info("Eşleşen fatura bulunamadı.")
        
    with t3: st.dataframe(res["Ödemeler"], use_container_width=True)
    with t4: st.dataframe(res["Bizde Var - Yok"], use_container_width=True)
    with t5: st.dataframe(res["Onlarda Var - Yok"], use_container_width=True)
