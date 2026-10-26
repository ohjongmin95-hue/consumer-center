// 법·제도 소식: 운영팀이 올린 소식. 누르면 펼치고, 출처는 앱 안 브라우저로 연다.
import * as WebBrowser from 'expo-web-browser';
import { useState } from 'react';
import { Pressable, Text, View } from 'react-native';
import { Card, Loading, Notice, Screen } from '../components/ui';
import { api, fmtDate } from '../lib/api';
import { C, FONT } from '../lib/theme';
import { useLoad } from '../lib/useLoad';

export default function News() {
  const { data, err, reload } = useLoad(api.news);
  const [open, setOpen] = useState(0);
  if (!data) return err ? <Notice text={err} /> : <Loading />;
  if (!data.news.length)
    return (
      <Screen>
        <Text style={{ fontFamily: FONT, fontSize: 15, color: C.fg3, padding: 24 }}>아직 올라온 소식이 없습니다.</Text>
      </Screen>
    );
  return (
    <Screen onRefresh={reload}>
      <View style={{ height: 8 }} />
      {data.news.map((n) => (
        <Card key={n.id}>
          <Pressable onPress={() => setOpen(open === n.id ? 0 : n.id)} style={{ gap: 6 }}>
            <Text style={{ fontFamily: FONT, fontSize: 13, color: C.fg3 }}>{fmtDate(n.created).replace(/ \d\d:\d\d$/, '')}</Text>
            <Text style={{ fontFamily: FONT, fontSize: 17, fontWeight: '700', color: C.fg, letterSpacing: -0.4 }}>{n.title}</Text>
          </Pressable>
          {open === n.id ? (
            <View style={{ gap: 12, marginTop: 10 }}>
              <Text style={{ fontFamily: FONT, fontSize: 15, lineHeight: 23, color: C.fg2 }}>{n.body}</Text>
              {n.source_url ? (
                <Pressable onPress={() => WebBrowser.openBrowserAsync(n.source_url!)}>
                  <Text style={{ fontFamily: FONT, fontSize: 14, fontWeight: '700', color: C.accentInk }}>출처 보기 ›</Text>
                </Pressable>
              ) : null}
            </View>
          ) : null}
        </Card>
      ))}
    </Screen>
  );
}
