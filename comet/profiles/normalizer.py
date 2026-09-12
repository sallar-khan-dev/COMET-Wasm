def normalize(value, minimum, maximum, direction):
    value = float(value)
    minimum = float(minimum)
    maximum = float(maximum)

    if maximum <= minimum:
        return 1.0

    x = (value - minimum) / (maximum - minimum)
    x = max(0.0, min(1.0, x))

    if direction == "high":
        return x

    if direction == "low":
        return 1.0 - x

    raise ValueError(
        f"Unknown normalization direction: {direction}"
    )


def normalize_metric(value, parameters):
    return normalize(
        value,
        parameters["minimum"],
        parameters["maximum"],
        parameters["direction"],
    )
