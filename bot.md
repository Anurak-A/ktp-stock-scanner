# Strategy Documentation — Stock Scanner

> โปรเจกต์นี้เป็น **Stock Scanner** สำหรับหุ้นอเมริกาและหุ้นไทย
> ใช้ strategy ด้านล่างเป็นตัว **recheck signal** บน **TF Daily เท่านั้น**
> ไม่มีการเข้า order อัตโนมัติ — แสดงผลเป็น scan result ให้ผู้ใช้ตัดสินใจเอง
> อัปเดตล่าสุด: มีนาคม 2026

---

## Strategy 1: White Line (WL)

### หลักการ

WL เป็น **Mean-Reversion strategy** ที่รอให้ราคา Overbought/Oversold (วัดด้วย Stochastic)
จากนั้นรอ **Swing High/Low** ก่อน แล้วรอ body ของแท่งเทียน D1 ทะลุผ่าน "เส้นขาว" (White Line)
เพื่อยืนยันการกลับทิศก่อนเข้า order

เสริมด้วยการตี Fibonacci 
**Fibonacci Reversal strategy** บน D1
ใช้ Fibonacci extension จาก swing OB/OS เพื่อหา "zone of interest"

### Fibonacci Structure

```
SELL Fibo: วัดจาก OB1 (Swing High) → OS2 (Swing Low ล่าสุด)
           ลาก Fibo extension ลงมา
           Valid levels: 0.382, 0.5, 0.618, 0.786, 1.382, 1.618, 2.0, 2.618

BUY Fibo:  วัดจาก OS1 (Swing Low แรก) → OB1 (Swing High ล่าสุด)
           ลาก Fibo extension ขึ้นไป
           Valid levels: 0.382, 0.5, 0.618, 0.786, 1.382, 1.618, 2.0, 2.618


```
### Sideway Structure   
```
Sell Side Way: วัดจาก OB1 (Swing High) → OS2 (Swing Low ล่าสุด)
               ลาก Fibo extension ลงมา
               ราคายังอยู่ในกรอบ 1.0 -> 0.0 โดยที่ไม่สามารถ break 1.0 (Low เดิม) ได้
Buy Side Way:  วัดจาก OS1 (Swing Low แรก) → OB1 (Swing High ล่าสุด)
               ลาก Fibo extension ขึ้นไป
               ราคายังอยู่ในกรอบ 0.0 -> 1.0 โดยที่ไม่สามารถ break 1.0 (High เดิม) ได้
```
### Trend Structure   
```
Sell Trend: วัดจาก OB1 (Swing High) → OS2 (Swing Low ล่าสุด)
               ลาก Fibo extension ลงมา
               ถ้าราคาเข้าโซน 50% → 1.382
Buy Trend:  วัดจาก OS1 (Swing Low แรก) → OB1 (Swing High ล่าสุด)
               ลาก Fibo extension ขึ้นไป
               ถ้าราคาเข้าโซน 50% → 1.382
```


### ขั้นตอน Signal สำหรับ Trend (ทีละขั้น)

```
1. Stochastic (9,3,3) เข้า OB zone (K > 79)  → รอ SELL setup
   - ถ้าเข้า OB Zone แล้ว K ยังไม่ <21 จะถือว่ายังอยู่ใน OB Zone
   Stochastic (9,3,3) เข้า OS zone (K < 21)  → รอ BUY  setup
   - ถ้าเข้า OS Zone แล้ว K ยังไม่ >79 จะถือว่ายังอยู่ใน OS Zone

2. ระหว่างอยู่ใน zone: ติดตาม Swing High (OB) หรือ Swing Low (OS)
   - Swing High = bar ที่มี High สูงสุดใน OB zone
   - Swing Low  = bar ที่มี Low ต่ำสุดใน OS zone

3. หลัง Swing High/Low เกิด → คำนวณ White Line:
   SELL: ดู bar ถัดจาก Swing High (bar+1, bar+2)
         → White Line = min(open, close) ของ bar แรกที่ต่ำกว่า min(open, close) ของ Swing bar
   BUY:  ดู bar ถัดจาก Swing Low (bar+1, bar+2)
         → White Line = max(open, close) ของ bar แรกที่สูงกว่า max(open, close) ของ Swing bar

4. Entry Signal:
   SELL: bar D1 close < White Line → signal SELL
   BUY:  bar D1 close > White Line → signal BUY

5. ในกรณีที่จะ recheck เมื่อเทียบกับ structure และต้องเป็น Trend
    SELL : Buy Fibo ต้องอยู่ในโซน 0.382, 0.5, 0.618, 0.786
    BUY : Sell Fibo ต้องอยู่ในโซน 0.382, 0.5, 0.618, 0.786

6. Reference SL / TP (แสดงเป็นข้อมูลประกอบ ไม่ได้เข้า order):
   SELL: SL ref = Swing High + buffer
   BUY:  SL ref = Swing Low  - buffer
   TP ref: entry ± (SL_distance × RR_ratio)
```
### ขั้นตอน Signal สำหรับ Sideway (ทีละขั้น)
```
1. Sell: ราคาใกล้เคียง 1.0 (Buy fibo) ของสวิงที่อยู่โซน OB และ มีไปอยู่ในโซน OS ก่อนที่ Sto จะอยู่ในโซน OB (ณ ปัจจุบัน) 
   Buy: ราคาใกล้เคียง 1.0 (Sell fibo) ของสวิงที่อยู่โซน OS และ มีไปอยู่ในโซน OB ก่อนที่ Sto จะอยู่ในโซน OS (ณ ปัจจุบัน)

2. มี rejection หรือ divergence ของ Sto

3. SL / TP:
   SELL: SL = Swing High + buffer (100 pts)
   BUY:  SL = Swing Low  - buffer (100 pts)
   TP:   50% ของช่วง 1.0 → 0.0
```


### Swing Reset Mode

ควบคุมว่าจะ "unlock" การเข้า trade ซ้ำบน swing เดิมได้เมื่อใด:

| Mode | พฤติกรรม |
|------|---------|
| `"A"` | Unlock เมื่อ new high/low ห่างจาก swing เดิม ≥ 500 pts |
| `"B"` | ไม่ unlock ในโซนเดิม (1 swing = 1 entry เท่านั้น) — **ค่าปัจจุบัน** |
| `"current"` | Unlock ทุกครั้งที่มี new high/low |

### Dynamic RR

```python
DYNAMIC_RR_ENABLED   = True
DYNAMIC_RR_THRESHOLD = 1000   # pts
DYNAMIC_RR_HIGH      = 1.3    # ใช้เมื่อ SL ≤ 1000 pts (signal แน่น)
DYNAMIC_RR_LOW       = 1.0    # ใช้เมื่อ SL > 1000 pts (signal กว้าง)
```

- SL ≤ 1000 pts → แสดงว่า swing compact → TP = SL × 1.3
- SL > 1000 pts → swing กว้าง → TP = SL × 1.0

---
