-- Миграция 002: эмитент бумаги (слой 1 «один эмитент»).
-- Бренд у бумаг одного эмитента разный (SBER и SBERP, акция и облигация МТС),
-- общий у них brands.company. issuer — вид для показа, issuer_key — casefold для сравнения.
ALTER TABLE instruments ADD COLUMN issuer TEXT;
ALTER TABLE instruments ADD COLUMN issuer_key TEXT;
CREATE INDEX idx_instruments_issuer_key ON instruments(issuer_key);
