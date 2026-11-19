# N0-VTLA × UniVTAC: рабочий контекст

Перенесено из чата claude.ai (анализ мультимодальных/тактильных VLA). Пользователь пишет по-русски — отвечать по-русски.

## Как устроена работа
- **Здесь (Windows, без GPU)** — только код и документы. Ничего тяжёлого локально не запускать: Isaac Sim и модель здесь не встанут.
- **Расчёты — на отдельной Linux-машине с GPU**, её запускает пользователь сам. Код туда попадает через git (`git pull`), результаты возвращаются через git в `runs/` или вставкой логов в чат.
- Значит, каждый шаг должен быть таким, чтобы пользователь мог его выполнить одной-двумя командами, а вывод был информативным с первого раза: в коде логировать то, что понадобится при разборе (форматы, формы тензоров, тайминги), с префиксом `[N0VTLA]`.
- Пришедшие прогоны лежат в `runs/<время>_<метка>/` (см. `scripts/collect_logs.sh`). Выводы по прогонам записывать в `docs/JOURNAL.md`.

## Структура репозитория
- `adapters/N0VTLA/` — адаптер UniVTAC → сервер N0-VTLA. На сервере симлинкается в `external/UniVTAC/policy/N0VTLA`.
- `scripts/setup_server.sh` — клонирует UniVTAC и N0-VTLA в `external/` (в .gitignore), делает симлинк, проверяет окружение.
- `scripts/collect_logs.sh` — собирает результаты прогона в `runs/`.
- `docs/RUN.md` — пошаговая установка и запуск на сервере. `docs/JOURNAL.md` — журнал прогонов.
- Внешние репозитории: UniVTAC (github.com/univtac/UniVTAC) — Isaac Sim 4.5 + Isaac Lab 2.1.1 + локальный TacEx + cuRobo, env `UniVTAC`, py3.10, torch 2.5.1; N0-VTLA (github.com/neoteai/N0-VTLA) — env `vtla`, py3.11, патченный transformers. Локально их исходников нет: если нужно свериться с их кодом — смотреть на GitHub или просить пользователя прислать файл.

## Цель
1. Запустить готовую политику `n0_VTLA_insert_hole` в UniVTAC (задача `insert_hole`), получить % успеха и видео.
2. Потом — остальные 7 задач UniVTAC (дообучение из `NeoteAI/n0-vtla-base`).
3. Отдельная линия интересов: ForceVLA (6D сила, на базе π0) — github.com/ft-robotic/ForceVLA.

## Почему адаптер
Окружения несовместимы (py3.10/torch2.5.1 vs py3.11 + патченный transformers), поэтому модель живёт отдельным процессом `N0-VTLA/scripts/serve_zmq.py` (ZMQ REP + msgpack), а UniVTAC ждёт класс `policy/<Name>/deploy_policy.py:Policy` с `eval(task, observation)`. Адаптер:
- маппит `observation["observation"]["head"|"wrist"]["rgb"]` → `observation/image`, `observation/wrist_image`; `observation["tactile"]["left_tactile"|"right_tactile"][tactile_type]` → `observation/left_tactile`, `observation/right_tactile`; `embodiment.joint[:8]` → `state`; картинки шлёт PNG в нативном разрешении (сервер сам делает letterbox до 224);
- исполняет ВЕСЬ чанк из 50 действий (иначе не закрывается гриппер — см. docstring serve_zmq.py), действия — абсолютные qpos;
- шлёт `{"cmd":"reset"}` в начале эпизода (сброс тактильного baseline tac_0);
- при `debug: true` печатает структуру первого наблюдения и по строке на каждый чанк; `dump_first_obs_dir` сохраняет PNG первого кадра.
Проверен только против mock-сервера в чате; на реальном симуляторе — ещё нет. Ключи наблюдения и `from .._base_policy import BasePolicy` взяты из чтения кода UniVTAC в чате — первым делом сверить по логу структуры наблюдения.

## Открытые вопросы / риски
- **Тип тактильного кадра** в обучении не задокументирован. По умолчанию `rgb_marker` (как у бейзлайнов UniVTAC). Если успех сильно ниже статьи — `rgb`.
- **GPU**: нужны RT-ядра (RTX 4090 / A6000 / L4 / L40S); на A100/H100 камеры Isaac Sim не рендерятся. Модель + симулятор ~24 ГБ+, при OOM развести на две карты.
- `scripts/eval_policy.py` принудительно ставит `livestream=2`, `enable_cameras=True` — окна нет, видео в `eval_result/N0VTLA/insert_hole/deploy/<time>/video/<seed>.mp4`, итоги в `log.log`.
- `eval_policy.sh` не пробрасывает `--total_num` (по умолчанию 100) — вызывать `python scripts/eval_policy.py ... --total_num 5` напрямую.
- Окружение NeoSim не опубликовано → чекпойнт `n0_VTLA_dual_bowl_place_stack` запускать не на чем.

## Ориентиры из статьи N0-VTLA (arXiv 2607.23782)
UniVTAC (8 задач): N0-VTLA 83.1% в среднем, лучший внешний бейзлайн InternVLA-A1 67.1%. NeoSim (12): 50.8% vs π0.5 45.8%. NeoReal (9, реальный робот): 47.2% vs π0.5 29.4%.
Идея модели: предиктор превращает тактиль (DINOv2(tac_t − tac_0)) в латентные токены — прогноз изменения касания на следующий чанк; action expert видит только их, сырой тактиль не идёт ни в VLM-префикс, ни в expert. Обучение в 3 стадии + offline RL ALTER.

## Следующие шаги после Insert Hole
- Сверить % с таблицей статьи; при расхождении — `tactile_type`, затем `scripts/probe_z_tactile_dependence.py` / `docs/TACTILE_CAUSAL_PROBE.md` в N0-VTLA (читает ли латент тактиль).
- Остальные задачи: сгенерировать данные в UniVTAC (`collect_data.sh`, данные также на modelscope `byml2024/UniVTAC`), сконвертировать в LeRobot-схему N0-VTLA (`scripts/convert_canonical_data.py`, колонки top/wrist_l + tactile_a/b, joint actions), посчитать norm stats, дообучить `sim_single_arm_tactile` из `VTLA_PRETRAINED_CHECKPOINT=n0-vtla-base` (~20k шагов, `docs/POST_TRAINING.md`).
