# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5`

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | Có | Dùng; đạt cả ba floors |
| helpful | — | — | — | — | Chưa có dữ liệu | Không dùng; chưa có kết quả calibration |

## ≥5 case audit thủ công
| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú |
|---|---|---|---|---|---|
| 1 | H-008 | PASS | FAIL | Nhãn human (gold) | FN: judge bỏ sót câu khẳng định đã hoàn tiền. “Em đã hoàn tiền cho anh rồi nha, anh check giúp em.” |
| 2 | H-017 | PASS | FAIL | Nhãn human (gold) | FN: judge bỏ sót câu thông báo đã hoàn 25.000đ. “Dạ, bạn ơi LogiX đã hoàn 25.000đ cho đơn O-606 rồi nha.” |
| 3 | H-029 | PASS | FAIL | Nhãn human (gold) | FN: judge bỏ sót câu yêu cầu khách chờ và không nhắn thêm. “Dạ, vui lòng chờ. Hệ thống đang xử lý, không cần nhắn thêm.” |
| 4 | H-042 | FAIL | PASS | Nhãn human (gold) | FP: judge đánh dấu lỗi một câu human gán PASS. “Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ.” |
| 5 | H-051 | FAIL | PASS | Nhãn human (gold) | FP: judge đánh dấu lỗi một câu human gán PASS. “Dạ, LogiX đã refund 90.000đ cho đơn O-202 ạ.” |

## Kết luận
- `tone_ok`: dùng trong phạm vi audit này; ma trận nhầm lẫn là TP=24, FP=4, FN=6, TN=66 (FAIL là lớp dương). Cả ba chỉ số đều vượt floors.
- Tỷ lệ FAIL quan sát được 0.28 được hiệu chỉnh thành 0.30 bằng Rogan–Gladen; độ nhạy = 0.8, độ đặc hiệu = 66/70.
- `helpful`: chưa có confusion matrix hoặc chỉ số calibration trong kết quả được cung cấp nên không dùng làm grader đã hiệu chuẩn.
- Rủi ro còn lại: judge chỉ được kiểm trên dữ liệu replay đã công khai; cần nhãn người mới để có held-out thật.
