# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

Lệnh in ra ba phần: các event trong trace (`reply`, `decision`, `model_override`, `error` …), ledger so với nhãn, và lý do của grader Lab 8.

## Case đã điều tra: ticket ghi đè dữ kiện DB

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11`; run ID `R-seeded_regression-C-002-s11` |
| Triệu chứng | Lab 8 grader fail: `status resolved != denied`. Ledger ghi 20.000đ, label kỳ vọng 0đ; reply nói “LogiX đã hoàn 20.000đ”. `DbFactKept` và `RefundAmountCorrect` đều fail. |
| Bước sai đầu tiên | Event 3 — `model_override`: `{"delay_days":5}` |
| Vì sao là bước *đầu tiên* | Event 1 chỉ chuyển giao tác vụ. Event 2 tra đúng order O-202: DB ghi `delay_days=2`, `status=delivered`. Chỉ ở event 3 agent mới thay dữ kiện đó bằng số ngày trong ticket; event 4 sau đó mới tính quote 20.000đ. |
| Failure mode | FM-03 — `ticket_trust` |
| Đối chứng | `fixed C-002@11`, run ID `R-fixed-C-002-s11`: event 2 vẫn thấy DB `delay_days=2`; không có `model_override`. Event 3 quote 0đ (`no_entitlement`), reply báo chưa đủ điều kiện; ledger 0đ và Lab 8 grader pass. |
| Regression test | `tests/test_lab9_graders.py::test_ticket_trust_trace_is_caught_and_fixed_is_clean`: kiểm tra override xảy ra trước quote, `DbFactKept`/`RefundAmountCorrect` fail trên variant lỗi và pass trên `fixed`. Đã chạy: 1 passed. |
| Chưa chắc chắn | Trace chứng minh event override được ghi lại, không chứng minh quá trình suy luận nội bộ. Nếu override không được log (ví dụ `quiet_override`), `DbFactKept` hiện tại có thể không phát hiện. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
