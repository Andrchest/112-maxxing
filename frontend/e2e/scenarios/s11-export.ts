// S11: exports: the admin's «Экспорт настроек (XML)» downloads without passwords or keys; the
// trainee's «Скачать профиль (JSON)» downloads without the password hash.
import { check, scenario } from './dsl';
import { downloadedToastCheck, loginSteps, navLink } from './steps';

export const S11 = scenario(
  'S11',
  'Экспорт: настройки (XML) без паролей и ключей, профиль стажёра (JSON) без хэша пароля',
  ['admin', 'trainee'],
  [
    ...loginSteps('admin', 'ADMIN', 'администратора (admin)'),
    {
      actor: 'admin',
      do: 'На странице «Администрирование» справа вверху нажать «Экспорт настроек (XML)» и открыть скачанный файл (например, перетащить его в новую вкладку браузера).',
      action: async (page, ctx) => {
        const file = await ctx.download(page, () => page.getByRole('button', { name: 'Экспорт настроек (XML)', exact: true }).click());
        ctx.vars.xmlName = file.fileName;
        ctx.vars.xml = file.text();
      },
      expect: [
        check('скачался файл `settings.xml`', async (_page, ctx) => {
          if (ctx.vars.xmlName !== 'settings.xml') throw new Error(`скачан файл «${ctx.vars.xmlName}»`);
        }),
        check('файл начинается с `<settings` и содержит строки `<setting name="SIM_…">`', async (_page, ctx) => {
          const xml = ctx.vars.xml ?? '';
          if (!xml.trimStart().startsWith('<settings') || !xml.includes('<setting name="SIM_')) throw new Error('не похоже на экспорт настроек');
        }),
        check('в файле нет слов SECRET, TOKEN= и пароля: единственное имя с PASSWORD — `SIM_MIN_PASSWORD_LENGTH`; нет адресов вида `postgresql://…@` и `redis://…@`', async (_page, ctx) => {
          const xml = ctx.vars.xml ?? '';
          const names = [...xml.matchAll(/name="([^"]+)"/g)].map((match) => match[1] ?? '');
          const bad = names.filter((name) => /SECRET|PASSWORD|API_KEY|TOKEN$/i.test(name) && name !== 'SIM_MIN_PASSWORD_LENGTH');
          if (bad.length > 0) throw new Error(`в файле есть ${bad.join(', ')}`);
          if (/(postgres(ql)?|redis)(\+\w+)?:\/\/[^<"]*@/i.test(xml)) throw new Error('в файле адрес базы с паролем');
        }),
        check('в файле нет паролей учётных записей admin, instructor, trainee', async (_page, ctx) => {
          const xml = ctx.vars.xml ?? '';
          for (const actor of ['admin', 'instructor', 'trainee']) {
            if (xml.includes(ctx.credentials(actor).password)) throw new Error(`в файле пароль ${actor}`);
          }
        }),
        downloadedToastCheck(() => 'settings.xml'),
      ],
    },
    ...loginSteps('trainee', 'TRAINEE', 'стажёра (trainee)'),
    {
      actor: 'trainee',
      do: 'В шапке, в меню, нажать «История»; справа вверху нажать «Скачать профиль (JSON)» и открыть скачанный файл.',
      action: async (page, ctx) => {
        await navLink(page, 'История').click();
        const file = await ctx.download(page, () => page.getByRole('button', { name: 'Скачать профиль (JSON)', exact: true }).click());
        ctx.vars.jsonName = file.fileName;
        ctx.vars.json = file.text();
      },
      expect: [
        check('скачался файл `profile-<логин>.json` (для trainee — `profile-trainee.json`)', async (_page, ctx) => {
          if (ctx.vars.jsonName !== `profile-${ctx.credentials('trainee').username}.json`) throw new Error(`скачан файл «${ctx.vars.jsonName}»`);
        }),
        check('в файле: `"username": "trainee"`, `"user_role": "TRAINEE"`, блок `"history"` с `session_count`', async (_page, ctx) => {
          const profile = JSON.parse(ctx.vars.json ?? '{}') as { username?: string; user_role?: string; history?: { session_count?: number } };
          if (profile.username !== ctx.credentials('trainee').username || profile.user_role !== 'TRAINEE' || profile.history?.session_count === undefined) {
            throw new Error('в профиле нет логина, роли или истории');
          }
        }),
        check('в файле нет слов password, hash, argon и самого пароля', async (_page, ctx) => {
          const json = ctx.vars.json ?? '';
          if (/password|hash|argon/i.test(json)) throw new Error('в профиле есть поле пароля или хэша');
          if (json.includes(ctx.credentials('trainee').password)) throw new Error('в профиле пароль');
        }),
        downloadedToastCheck((ctx) => ctx.vars.jsonName ?? ''),
      ],
    },
  ],
  {
    purpose:
      'Выгрузки не раскрывают секреты: «Экспорт настроек (XML)» у администратора — только несекретные настройки; «Скачать профиль (JSON)» у стажёра — данные и итоги без пароля и его хэша.',
    preconditions: ['Вход ещё не выполнен ни в одной вкладке (или нажмите «Выйти» во всех). Браузер сохраняет скачанные файлы.'],
    testData: ['Учётные записи `admin` и `trainee`. Ничего не создаётся.'],
    cleanup: [],
  },
);
