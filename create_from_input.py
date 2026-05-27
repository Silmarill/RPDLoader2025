import re
import csv
import os
from datetime import datetime
from playwright.sync_api import sync_playwright
from config import *


STEP = 0

os.makedirs(LOG_DIR, exist_ok=True)

STAMP = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
STEPS_LOG_FILE = os.path.join(LOG_DIR, f"steps_from_input_{STAMP}.txt")
REPORT_FILE = os.path.join(LOG_DIR, f"rpd_from_input_report_{STAMP}.csv")


class AlreadyCreatedException(Exception):
    pass


def log(message):
    global STEP
    STEP += 1
    line = f"[ШАГ {STEP:04d}] {message}"
    print(line)

    with open(STEPS_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def normalize_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_for_compare(text):
    text = normalize_text(text).lower()
    text = text.replace("ё", "е")
    text = text.replace("\u00a0", " ")
    return normalize_text(text)


def parse_direction_program(value):
    parts = value.split(" - ", 1)
    if len(parts) != 2:
        raise Exception(f"Не могу разобрать направление и ООП: {value}")
    return normalize_text(parts[0]), normalize_text(parts[1])


def read_input_rows():
    rows = []

    log(f"Читаю входной файл: {INPUT_FILE}")

    with open(INPUT_FILE, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f, delimiter=";")

        for row_num, row in enumerate(reader, start=1):
            if not row or len(row) < 4:
                continue

            study_year = normalize_text(row[0])
            direction_program = normalize_text(row[1])
            discipline = normalize_text(row[2])
            admission_year = normalize_text(row[3])
            user_name = normalize_text(row[4]) if len(row) >= 5 else ""

            if not study_year or not direction_program or not discipline or not admission_year:
                raise Exception(f"Строка {row_num}: есть пустые поля: {row}")

            direction_code, program_name = parse_direction_program(direction_program)

            rows.append({
                "row_num": row_num,
                "study_year": study_year,
                "direction_code": direction_code,
                "program_name": program_name,
                "discipline": discipline,
                "admission_year": admission_year,
                "user_name": user_name,
            })

    log(f"Строк во входном файле: {len(rows)}")
    return rows


def select_option_by_text(select_locator, wanted_text, label="select", timeout_ms=10000):
    wanted = normalize_text(wanted_text).lower()

    log(f"Ищу пункт в списке '{label}': {wanted_text}")

    select_locator.locator("option").first.wait_for(
        state="attached",
        timeout=timeout_ms
    )

    options = select_locator.locator("option")
    exact_match = None
    partial_match = None

    for i in range(options.count()):
        option = options.nth(i)

        value = option.get_attribute("value")
        text = normalize_text(option.inner_text())
        title = normalize_text(option.get_attribute("title") or "")

        if not value or "Выберите" in text:
            continue

        text_l = text.lower()
        title_l = title.lower()
        value_l = normalize_text(value).lower()

        if wanted == text_l or wanted == title_l or wanted == value_l:
            exact_match = value
            log(f"Найдено точное совпадение в '{label}': {text}")
            break

        if wanted in text_l or wanted in title_l or text_l in wanted:
            partial_match = value
            log(f"Найдено частичное совпадение в '{label}': {text}")

    if exact_match:
        select_locator.select_option(exact_match)
        return exact_match

    if partial_match:
        select_locator.select_option(partial_match)
        return partial_match

    available = []
    for i in range(options.count()):
        text = normalize_text(options.nth(i).inner_text())
        if text:
            available.append(text)

    raise Exception(
        f"Не найден пункт '{wanted_text}' в списке '{label}'. "
        f"Доступные варианты: {available}"
    )


def select_first_real_option(select_locator, label="select", timeout_ms=10000):
    log(f"Жду варианты в списке: {label}")

    select_locator.locator("option[value]:not([value=''])").first.wait_for(
        state="attached",
        timeout=timeout_ms
    )

    options = select_locator.locator("option")

    for i in range(options.count()):
        value = options.nth(i).get_attribute("value")
        text = normalize_text(options.nth(i).inner_text())

        if not value or "Выберите" in text:
            continue

        log(f"Выбираю пункт меню: {text}")
        select_locator.select_option(value)
        return value

    raise Exception(f"Не найден вариант в списке: {label}")


def go_to_create_page(page):
    log("Перехожу на страницу создания РПД")
    page.goto("https://eios.kemsu.ru/a/workProgram/")

    log("Нажимаю 'Добавить новую РПД'")
    page.get_by_role("button", name="Добавить новую РПД").click()


def fill_create_filters(page, item):
    log("Выставляю фильтры на странице создания РПД")

    log(f"Институт: {INSTITUTE_ID}")
    page.get_by_role("combobox").first.select_option(INSTITUTE_ID)

    log(f"Направление: {item['direction_code']}")
    page.get_by_role("combobox").nth(1).select_option(item["direction_code"])
    page.wait_for_timeout(500)

    log(f"Учебный год: {item['study_year']}")
    page.get_by_role("combobox").nth(2).select_option(item["study_year"])
    page.wait_for_timeout(500)

    log(f"ООП: {item['program_name']}")
    select_option_by_text(
        page.get_by_role("combobox").nth(3),
        item["program_name"],
        "ООП"
    )
    page.wait_for_timeout(1000)

    log(f"Год набора: {item['admission_year']}")
    page.get_by_role("combobox").nth(4).select_option(item["admission_year"])
    page.wait_for_timeout(500)

    plan_select = page.locator("select").nth(5)
    select_first_real_option(plan_select, "учебный план")
    page.wait_for_timeout(1000)


def select_discipline_for_create(page, discipline_name):
    log(f"Ищу дисциплину для создания: {discipline_name}")

    discipline_select = page.locator("div:nth-child(7) > .col > .form-control")
    discipline_select.locator("option").first.wait_for(state="attached", timeout=10000)

    options = discipline_select.locator("option")
    found_same_name_but_created = False

    for i in range(options.count()):
        option = options.nth(i)

        value = option.get_attribute("value")
        text = normalize_text(option.inner_text())
        title = normalize_text(option.get_attribute("title") or "")

        if not value or "Выберите" in text:
            continue

        same = (
            normalize_for_compare(discipline_name) == normalize_for_compare(title)
            or normalize_for_compare(discipline_name) in normalize_for_compare(text)
        )

        if not same:
            continue

        if "РПД создана" in text:
            found_same_name_but_created = True
            continue

        log(f"Выбираю дисциплину: {text}")
        discipline_select.select_option(value)
        return value

    if found_same_name_but_created:
        raise AlreadyCreatedException(f"РПД уже создана: {discipline_name}")

    raise Exception(f"Не найдена дисциплина в списке создания: {discipline_name}")


def select_discipline_filter_by_name(page, discipline_name):
    log(f"Выбираю дисциплину в фильтре: {discipline_name}")

    wanted = normalize_for_compare(discipline_name)

    for attempt in range(1, 6):
        log(f"Попытка выбора дисциплины в фильтре: {attempt}/5")

        selects = page.locator("select.form-control.form-control-sm")

        for i in range(selects.count()):
            select = selects.nth(i)
            text = normalize_text(select.inner_text())

            if "Выберите дисциплину" not in text:
                continue

            options = select.locator("option")
            available = []

            for j in range(options.count()):
                option = options.nth(j)

                value = option.get_attribute("value")
                option_text = normalize_text(option.inner_text())
                title = normalize_text(option.get_attribute("title") or "")

                if not value or value == "-1":
                    continue

                available.append(option_text)

                option_text_cmp = normalize_for_compare(option_text)
                title_cmp = normalize_for_compare(title)

                if (
                    wanted == option_text_cmp
                    or wanted == title_cmp
                ):
                    log(f"Выбрана дисциплина в фильтре: {option_text}")
                    select.select_option(value)
                    return

            log(f"Дисциплина пока не найдена. Вариантов в фильтре: {len(available)}")

        page.wait_for_timeout(500)

    raise Exception(f"Не найдена дисциплина в фильтре после 5 попыток: {discipline_name}")


def set_user_program_filters_and_get_list(page, item):
    log("Жду таблицу РПД")
    page.locator("table").first.wait_for(state="visible", timeout=30000)
    page.wait_for_timeout(1500)

    log("Выставляю фильтры в списке РПД")

    selects = page.locator("select.form-control.form-control-sm")

    direction_set = False
    study_year_set = False
    admission_year_set = False

    for i in range(selects.count()):
        select = selects.nth(i)
        text = normalize_text(select.inner_text())

        if "Выберите напр-е" in text:
            log(f"Фильтр направление: {item['direction_code']}")
            select.select_option(item["direction_code"])
            direction_set = True
            page.wait_for_timeout(300)

        elif "Выберите учебный год" in text:
            log(f"Фильтр учебный год: {item['study_year']}")
            select.select_option(item["study_year"])
            study_year_set = True
            page.wait_for_timeout(300)

        elif "Выберите год" in text:
            log(f"Фильтр год набора: {item['admission_year']}")
            select.select_option(item["admission_year"])
            admission_year_set = True
            page.wait_for_timeout(300)

    if not direction_set or not admission_year_set or not study_year_set:
        log("Не все фильтры распознаны по тексту. Пробую fallback по порядку select")

        # Обычно фильтры в таблице идут так:
        # 0 — направление
        # 1 — год набора
        # 2 — учебный год
        # 3 — дисциплина
        try:
            log(f"Fallback направление: {item['direction_code']}")
            selects.nth(0).select_option(item["direction_code"])
            page.wait_for_timeout(300)

            log(f"Fallback год набора: {item['admission_year']}")
            selects.nth(1).select_option(item["admission_year"])
            page.wait_for_timeout(300)

            log(f"Fallback учебный год: {item['study_year']}")
            selects.nth(2).select_option(item["study_year"])
            page.wait_for_timeout(300)

        except Exception as e:
            log(f"Fallback фильтров не сработал: {e}")
            raise

    page.wait_for_timeout(500)
    select_discipline_filter_by_name(page, item["discipline"])

    log("Нажимаю 'Получить список РПД'")
    page.get_by_role("button", name="Получить список РПД").first.click()
    page.wait_for_timeout(2500)


def get_filtered_row(page, item):
    log(f"Ищу строку РПД: {item['discipline']} / {item['admission_year']}")

    for attempt in range(1, 6):
        log(f"Попытка найти строку РПД: {attempt}/5")

        try:
            rows = page.locator("tbody tr")
            rows.first.wait_for(state="attached", timeout=7000)

            for i in range(rows.count()):
                row = rows.nth(i)
                text = normalize_text(row.inner_text())

                if (
                    item["direction_code"] in text
                    and item["study_year"] in text
                    and item["admission_year"] in text
                    and item["discipline"] in text
                ):
                    log("Строка РПД найдена")
                    return row

            log(f"Строки есть, но нужная не найдена. Всего строк: {rows.count()}")

        except Exception as e:
            log(f"Строка пока не найдена: {e}")

        buttons = page.get_by_role("button", name="Получить список РПД")
        if buttons.count() > 0:
            log("Повторно нажимаю 'Получить список РПД'")
            buttons.first.click(timeout=10000)

        page.wait_for_timeout(2500)

    raise Exception(f"Строка РПД не найдена после повторных попыток: {item['discipline']}")


def extract_rpd_id_from_row(row):
    forms = row.locator("form")

    for i in range(forms.count()):
        action = forms.nth(i).get_attribute("action") or ""
        match = re.search(r"/work-prog2/(\d+)", action)
        if match:
            return match.group(1)

    return ""


def open_created_program(page, item):
    set_user_program_filters_and_get_list(page, item)

    row = get_filtered_row(page, item)

    rpd_id = extract_rpd_id_from_row(row)
    log(f"ID созданной РПД: {rpd_id}")

    log("Открываю созданную РПД")
    with page.expect_popup() as popup_info:
        row.locator("td").nth(7).click()

    return popup_info.value, rpd_id


def extract_years_from_copy_option(text, title):
    full = normalize_text(f"{text} {title}")
    matches = re.findall(r"/\s*(\d{4}-\d{4})\s*/\s*(\d{4})", full)

    if not matches:
        return None, None

    return matches[-1]


def select_copy_source(page1, item):
    log("Выбираю источник копирования")
    log("Правило: только дисциплина → НЕ текущий учебный год → самый новый учебный год → самый новый год набора")

    wanted_discipline = normalize_for_compare(item["discipline"])
    current_study_year = item["study_year"]

    copy_select = page1.get_by_role("combobox").nth(1)
    copy_select.locator("option").first.wait_for(state="attached", timeout=10000)

    options = copy_select.locator("option")
    candidates = []
    available = []

    for i in range(options.count()):
        option = options.nth(i)

        value = option.get_attribute("value")
        text = normalize_text(option.inner_text())
        title = normalize_text(option.get_attribute("title") or "")

        if not value:
            continue

        available.append(text)

        option_discipline = normalize_for_compare(text.split("/", 1)[0])

        if option_discipline != wanted_discipline:
            continue

        study_year, admission_year = extract_years_from_copy_option(text, title)

        if not study_year or not admission_year:
            log(f"Пропускаю: не смог извлечь годы из варианта: {text}")
            continue

        if study_year == current_study_year:
            log(
                f"Пропускаю источник из текущего учебного года "
                f"{study_year}, чтобы не копировать РПД саму в себя: {text}"
            )
            continue

        log(
            f"Кандидат: учебный_год={study_year}, "
            f"год_набора={admission_year}, value={value}, text={text}"
        )

        candidates.append({
            "value": value,
            "text": text,
            "study_year": study_year,
            "admission_year": admission_year,
        })

    if not candidates:
        log("Не найдено кандидатов по названию дисциплины вне текущего учебного года")
        log("Доступные варианты для копирования:")

        for idx, item_text in enumerate(available, start=1):
            log(f"  {idx}. {item_text}")

        raise Exception(
            f"Не найден источник копирования вне текущего учебного года: {item['discipline']}"
        )

    candidates.sort(
        key=lambda c: (
            int(c["study_year"].split("-")[0]),
            int(c["study_year"].split("-")[1]),
            int(c["admission_year"]),
        ),
        reverse=True
    )

    log("Отсортированные кандидаты:")
    for idx, candidate in enumerate(candidates, start=1):
        log(
            f"  {idx}. учебный_год={candidate['study_year']}, "
            f"год_набора={candidate['admission_year']}, "
            f"text={candidate['text']}"
        )

    best = candidates[0]

    log(f"Источник копирования выбран автоматически: {best['text']}")
    copy_select.select_option(best["value"])

    return best


def attach_user_to_rpd(page1, item):
    user_names_raw = item.get("user_name", "")

    if not user_names_raw:
        log("Пользователь для привязки не указан. Пропускаю привязку")
        return False

    user_names = [
        normalize_text(x)
        for x in user_names_raw.split("|")
        if normalize_text(x)
    ]

    attached_any = False

    log("Жду завершения копирования перед переходом к пользователям")
    page1.wait_for_timeout(3000)

    log("Открываю вкладку 'Пользователи'")
    page1.get_by_role("link", name="Пользователи").click()
    page1.wait_for_timeout(1000)

    for user_name in user_names:
        user_attached = False

        for attempt in range(1, 3):
            log(f"Попытка привязать пользователя {attempt}/3: {user_name}")

            search_box = page1.get_by_role(
                "textbox",
                name="Введите Ф. И. О. или логин пользователя"
            )

            search_box.click()
            search_box.fill("")
            search_box.fill(user_name)

            log("Нажимаю 'Найти'")
            page1.get_by_role("button", name="Найти").click()
            page1.wait_for_timeout(1000)

            plus_buttons = page1.get_by_role("button", name="+")
            count = plus_buttons.count()

            log(f"Найдено кнопок '+' для добавления пользователя: {count}")

            if count == 0:
                page1.wait_for_timeout(1000)
                continue

            log(f"Нажимаю '+' для привязки пользователя: {user_name}")
            plus_buttons.first.click()
            page1.wait_for_timeout(1000)

            log(f"Пользователь привязан: {user_name}")
            user_attached = True
            attached_any = True
            break   

        if not user_attached:
            log(f"ВНИМАНИЕ: пользователь не привязан после 3 попыток: {user_name}")
            continue

    return attached_any


def try_click_get_list_if_exists(page):
    buttons = page.get_by_role("button", name="Получить список РПД")
    count = buttons.count()

    log(f"Кнопок 'Получить список РПД' найдено: {count}")

    if count == 0:
        return False

    try:
        log("Нажимаю 'Получить список РПД'")
        buttons.first.click(timeout=5000)
        page.wait_for_timeout(2000)
        return True
    except Exception as e:
        log(f"Не удалось нажать 'Получить список РПД': {e}")
        return False


def approve_after_copy(page, item):
    log("Возвращаюсь в список РПД")
    page.get_by_role("link", name="Рабочие программы пользователя").click()
    page.wait_for_timeout(2000)

    try_click_get_list_if_exists(page)

    row = get_filtered_row(page, item)

    log("Нажимаю 'Утв'")
    row.get_by_role("button", name="Утв").click()
    page.wait_for_timeout(1500)


def make_report_row(
    item,
    created_rpd_id,
    status,
    created_ok,
    source,
    copied_ok,
    user_attached_ok,
    approved_ok,
    step_start,
    step_end,
    error,
):
    return [
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        LOGIN,
        item["study_year"],
        item["direction_code"],
        item["program_name"],
        item["admission_year"],
        item["discipline"],
        created_rpd_id,
        status,
        created_ok,
        source.get("text", "") if source else "",
        source.get("value", "") if source else "",
        source.get("study_year", "") if source else "",
        source.get("admission_year", "") if source else "",
        copied_ok,
        item.get("user_name", ""),
        user_attached_ok,
        approved_ok,
        step_start,
        step_end,
        error,
    ]


def save_report(report_rows):
    log(f"Сохраняю отчёт: {REPORT_FILE}")

    with open(REPORT_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow([
            "ДатаВремя",
            "Логин",
            "УчебныйГод",
            "Направление",
            "ООП",
            "ГодНабора",
            "Дисциплина",
            "ID_Созданной_РПД",
            "Статус",
            "Создана",
            "ИсточникКопирования",
            "ID_Источника",
            "УчебныйГодИсточника",
            "ГодИсточника",
            "Скопирована",
            "Пользователь",
            "ПользовательПривязан",
            "Утверждена",
            "ШагНачала",
            "ШагЗавершения",
            "Ошибка",
        ])
        writer.writerows(report_rows)


def run():
    input_rows = read_input_rows()
    report_rows = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=False,
            slow_mo=SLOW_MO
        )

        context = browser.new_context()
        page = context.new_page()

        log("Открываю главную страницу")
        page.goto("https://eios.kemsu.ru/main")

        log("Ввожу логин")
        page.get_by_role("textbox", name="логин").fill(LOGIN)

        log("Ввожу пароль")
        page.get_by_role("textbox", name="пароль").fill(PASSWORD)

        log("Нажимаю 'Войти'")
        page.get_by_role("button", name="Войти").click()

        log("Открываю раздел создания РПД")
        page.get_by_role("link", name="Создание рабочих программ дисциплин (ВО)").click()

        for item in input_rows:
            page1 = None

            step_start = STEP
            created_rpd_id = ""
            created_ok = False
            copied_ok = False
            user_attached_ok = False
            approved_ok = False
            source = None

            try:
                print(f"\n===== {item['discipline']} / {item['admission_year']} =====")

                go_to_create_page(page)
                fill_create_filters(page, item)

                select_discipline_for_create(page, item["discipline"])

                log("Нажимаю 'Создать программу'")
                page.get_by_role("button", name=re.compile("Создать программу")).click()
                created_ok = True
                page.wait_for_timeout(1500)

                log("Перехожу в 'Рабочие программы пользователя'")
                page.get_by_role("link", name="Рабочие программы пользователя").click()

                page1, created_rpd_id = open_created_program(page, item)

                log("Открываю вкладку 'Копирование'")
                page1.get_by_role("link", name="Копирование").click()

                log(f"Выбираю направление в копировании: {item['direction_code']}")
                page1.get_by_role("combobox").first.select_option(item["direction_code"])

                source = select_copy_source(page1, item)

                log("Нажимаю 'Скопировать'")
                page1.get_by_role("button", name="Скопировать").click()
                copied_ok = True
                page1.wait_for_timeout(3000)

                user_attached_ok = attach_user_to_rpd(page1, item)

                approve_after_copy(page1, item)
                approved_ok = True

                log("Закрываю вкладку РПД")
                page1.close()
                page1 = None

                report_rows.append(make_report_row(
                    item,
                    created_rpd_id,
                    "OK",
                    created_ok,
                    source,
                    copied_ok,
                    user_attached_ok,
                    approved_ok,
                    step_start,
                    STEP,
                    "",
                ))

            except AlreadyCreatedException as e:
                error = str(e)
                print(f"\nПРОПУСК: {item['discipline']} / {item['admission_year']} — {error}")

                report_rows.append(make_report_row(
                    item,
                    created_rpd_id,
                    "SKIPPED_ALREADY_CREATED",
                    created_ok,
                    source,
                    copied_ok,
                    user_attached_ok,
                    approved_ok,
                    step_start,
                    STEP,
                    error,
                ))

                try:
                    if page1:
                        page1.close()
                except:
                    pass

            except Exception as e:
                error = str(e)
                print(f"\nОШИБКА: {item['discipline']} / {item['admission_year']} — {error}")

                report_rows.append(make_report_row(
                    item,
                    created_rpd_id,
                    "ERROR",
                    created_ok,
                    source,
                    copied_ok,
                    user_attached_ok,
                    approved_ok,
                    step_start,
                    STEP,
                    error,
                ))

                try:
                    if page1:
                        page1.close()
                except:
                    pass

        save_report(report_rows)

        print(f"\nГотово.")
        print(f"Отчёт: {REPORT_FILE}")
        print(f"Лог шагов: {STEPS_LOG_FILE}")

        context.close()
        browser.close()


run()