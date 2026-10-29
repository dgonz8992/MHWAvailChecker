from datetime import datetime

availability = {
    "Alex Britton": ["12/8", "12/15", "12/21", "12/22", "1/4", "1/5", "1/11", "1/12", "1/18", "1/19", "1/25", "1/26"],
    "Jarrett Renshaw": ["11/3", "11/16", "11/23", "12/1", "12/7", "12/8", "12/14", "12/15", "12/22", "12/28", "12/29", "1/4", "1/11", "1/12", "1/18", "1/19", "1/25", "1/26"],
    "Tyler McGinnis": ["11/3", "11/10", "11/16", "12/1", "12/7", "12/8", "12/14", "12/15", "12/21", "12/22", "12/28", "12/29", "1/4", "1/5", "1/11", "1/12", "1/18", "1/19", "1/25", "1/26"]
}

openDates = [
    "11/3", "11/10", "11/16", "11/23",
    "12/1", "12/7", "12/8", "12/14", "12/15",
    "12/21", "12/22", "12/28", "12/29",
    "1/4", "1/5", "1/11", "1/12",
    "1/18", "1/19", "1/25", "1/26"
]

schedule = {}
gigCounts = {}

lastBooked = {}

for performer in availability:
    gigCounts[performer] = 0

for date in openDates:
    month = int(date.split("/")[0])
    year = 2026 if month >= 11 else 2027

    currentDate = datetime.strptime(f"{date}/{year}", "%m/%d/%Y")
    selected = None

    for performer in availability:
        if date in availability[performer]:

            if performer in lastBooked:
                gap = (currentDate - lastBooked[performer]).days

                if gap < 7:
                    continue

            if selected is None or gigCounts[performer] < gigCounts[selected]:
                selected = performer

    if selected is not None:
        schedule[date] = selected
        gigCounts[selected] += 1
        lastBooked[selected] = currentDate
        print(date, selected)
    else:
        print(date, "No one available.")

print(gigCounts)