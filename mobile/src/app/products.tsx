// 상품정보: 상담창 AI가 가격·재고·사용법 문의에 답할 때 본다. 엑셀(CSV)로 한꺼번에 올리기는 홈페이지에서.
import { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Btn, Card, Chips, Field, Loading, Notice, Screen } from '../components/ui';
import { api, Product, Products } from '../lib/api';
import { useAuth } from '../lib/auth';
import { C, FONT } from '../lib/theme';
import { errText, useLoad } from '../lib/useLoad';

const EMPTY: Product = { id: 0, name: '', price: '', stock: '', info: '' };

export default function ProductsScreen() {
  const { data, setData, err, token, reload } = useLoad(api.products);
  const [ok, setOk] = useState('');
  if (!data) return err ? <Notice text={err} /> : <Loading />;
  const saved = (d: Products, m: string) => (setData(d), setOk(m));
  return (
    <Screen onRefresh={reload}>
      <View style={st.head}>
        <Text style={st.p}>
          상품 가격·재고·사용법을 적어 두면 상담창에서 상품 문의에 바로 답합니다.{data.ai ? '' : ' (AI 상담이 켜지면 사용돼요)'} 엑셀로 한꺼번에 올리기는 홈페이지의 자동 처리 화면에서 할 수 있어요.
        </Text>
      </View>
      <Notice text={ok} tone="ok" />
      <ProductCard key={'new' + data.products.length} p={EMPTY} stocks={data.stocks} token={token} onSaved={saved} />
      {data.products.map((p) => (
        <ProductCard key={p.id} p={p} stocks={data.stocks} token={token} onSaved={saved} />
      ))}
    </Screen>
  );
}

function ProductCard({ p, stocks, token, onSaved }: { p: Product; stocks: Products['stocks']; token: string; onSaved: (d: Products, msg: string) => void }) {
  const { logout } = useAuth();
  const isNew = !p.id;
  const [open, setOpen] = useState(false);
  const [f, setF] = useState(p);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const stockLabel = stocks.find((x) => x.value === f.stock)?.label ?? stocks[0]?.label ?? '';
  const send = async (body: Partial<Product> & { act?: 'delete' }) => {
    setBusy(true);
    setErr('');
    try {
      const d = await api.saveProduct(token, body);
      onSaved(d, d.message || '저장했습니다');
      setOpen(false);
    } catch (e) {
      setErr(errText(e, logout));
    } finally {
      setBusy(false);
    }
  };
  if (!open)
    return (
      <Card>
        {isNew ? (
          <Btn title="상품 추가" kind="soft" onPress={() => (setF(EMPTY), setOpen(true))} />
        ) : (
          <View style={{ gap: 10 }}>
            <Text style={st.name}>{p.name}</Text>
            <Text style={st.sub}>{[p.price, stocks.find((x) => x.value === p.stock && x.value)?.label].filter(Boolean).join(' · ') || '가격·재고 미입력'}</Text>
            {p.info ? (
              <Text style={st.sub} numberOfLines={2}>
                {p.info}
              </Text>
            ) : null}
            <Btn title="고치기" kind="gray" onPress={() => setOpen(true)} />
          </View>
        )}
      </Card>
    );
  return (
    <Card>
      <View style={{ gap: 12 }}>
        <Field label="상품 이름" value={f.name} onChangeText={(name) => setF({ ...f, name })} maxLength={60} />
        <Field label="가격" value={f.price} onChangeText={(price) => setF({ ...f, price })} placeholder="예: 29,000원" maxLength={30} />
        <Text style={st.label}>재고</Text>
        <Chips items={stocks.map((x) => x.label)} value={stockLabel} onChange={(l) => setF({ ...f, stock: stocks.find((x) => x.label === l)?.value ?? '' })} />
        <Field label="안내" value={f.info} onChangeText={(info) => setF({ ...f, info })} multiline placeholder="사용법, 사이즈, 주의사항 등" maxLength={1000} />
        <Notice text={err} flat />
        <View style={{ flexDirection: 'row', gap: 8 }}>
          <Btn title="취소" kind="gray" onPress={() => (setOpen(false), setF(p))} style={{ flex: 1 }} />
          {isNew ? null : <Btn title="삭제" kind="danger" onPress={() => send({ id: p.id, act: 'delete' })} disabled={busy} style={{ flex: 1 }} />}
          <Btn title="저장" onPress={() => send(isNew ? { name: f.name, price: f.price, stock: f.stock, info: f.info } : f)} busy={busy} style={{ flex: 2 }} />
        </View>
      </View>
    </Card>
  );
}

const st = StyleSheet.create({
  head: { paddingHorizontal: 24, paddingTop: 8, paddingBottom: 16 },
  p: { fontFamily: FONT, fontSize: 15, lineHeight: 23, color: C.fg2 },
  name: { fontFamily: FONT, fontSize: 16, fontWeight: '700', color: C.fg },
  sub: { fontFamily: FONT, fontSize: 14, lineHeight: 21, color: C.fg2 },
  label: { fontFamily: FONT, fontSize: 14, fontWeight: '600', color: C.fg2 },
});
