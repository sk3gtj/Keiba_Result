import os
import json
import gspread
import re
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = "1ZOYEDVMpLfn8U-gFL5F3Rx_MdKsts6b2uUCSpPbwhjo"

def get_pcode(place):
    # 競馬場名からコードへ変換。部分一致にも対応。
    if '京都' in place: return '08'
    if '東京' in place: return '05'
    if '小倉' in place: return '10'
    if '中山' in place: return '06'
    if '阪神' in place: return '09'
    if '中京' in place: return '07'
    return '08'

def main():
    gcp_json = os.environ.get("GCP_JSON")
    target_date_input = os.environ.get("TARGET_DATE") # 例: 0210
    
    # 2026年固定。日付から数字だけ抜いてURL用に整形
    date_num = re.sub(r'[^0-9]', '', target_date_input)
    target_date_full = "2026" + date_num

    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(json.loads(gcp_json), scopes=scopes)
    client = gspread.authorize(creds)
    
    # シート名に「0210」が含まれるものを探す
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    worksheets = spreadsheet.worksheets()
    sheet = None
    for ws in worksheets:
        if target_date_input in ws.title:
            sheet = ws
            break
    
    if sheet is None:
        print(f"Error: Worksheet '{target_date_input}' not found")
        return

    # A3:C17のデータを一括取得
    records = sheet.get("A3:C17")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        current_place = ""
        for i, row in enumerate(records):
            if len(row) < 3 or not row[1] or not row[2]: 
                continue # R数や馬番が空ならスキップ
            
            place = row[0] if row[0] != "" else current_place
            current_place = place
            race_no = str(row[1]).zfill(2)
            umaban = str(row[2])
            
            p_code = get_pcode(place)
            print(f"--- 検索中: {place} {race_no}R {umaban}番 ---")
            
            # 開催回(k)と日目(d)を広めに探索
            found = False
            for k in range(1, 6):
                for d in range(1, 13):
                    race_id = f"{target_date_full}{p_code}{str(k).zfill(2)}{str(d).zfill(2)}{race_no}"
                    url = f"https://race.netkeiba.com/race/result.html?race_id={race_id}"
                    
                    page.goto(url, wait_until="domcontentloaded")
                    
                    # 結果テーブルがあるか確認
                    if page.query_selector("#All_Result_Table"):
                        soup = BeautifulSoup(page.content(), "html.parser")
                        
                        # 馬番の行を特定
                        target_row = None
                        for tr in soup.select("#All_Result_Table tbody tr"):
                            if f"<div>{umaban}</div>" in str(tr):
                                target_row = tr
                                break
                        
                        if target_row:
                            rank = target_row.select_one(".Rank").text.strip()
                            tan = "0"
                            fuku = "0"
                            
                            # 単勝取得
                            if rank == "1":
                                tan_tag = soup.select_one("tr.Tansho .Payout span")
                                if tan_tag: tan = tan_tag.text.replace(",","").replace("円","")
                            
                            # 複勝取得
                            if rank.isdigit() and int(rank) <= 3:
                                fuku_row = soup.select_one("tr.Fukusho")
                                if fuku_row:
                                    # 複勝リストの中から自分の馬番の位置を探す
                                    uma_list = [s.text.strip() for s in fuku_row.select(".Result span") if s.text.strip()]
                                    payout_list = fuku_row.select_one(".Payout span").decode_contents().split("<br/>")
                                    if umaban in uma_list:
                                        idx = uma_list.index(umaban)
                                        fuku = re.sub(r'[^0-9]', '', payout_list[idx])

                            # シート更新 (H:8, I:9, J:10)
                            row_num = i + 3
                            sheet.update_cell(row_num, 8, rank)
                            sheet.update_cell(row_num, 9, tan)
                            sheet.update_cell(row_num, 10, fuku)
                            print(f"✅ 更新成功: {rank}着 / 単{tan} / 複{fuku}")
                            found = True
                            break
                if found: break
            if not found:
                print(f"❌ データが見つかりませんでした: {place} {race_no}R")
        
        browser.close()

if __name__ == "__main__":
    main()
