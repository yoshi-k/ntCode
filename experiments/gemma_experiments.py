import matplotlib.pyplot as plt
import numpy as np
import math
from pathlib import Path


def plot_simple_functions(output_path: str = "experiments/gemma_plot.png") -> None:
    """Create a plot of f(x)=x^2-2 and g(x)=x+2 with the intersection marked (Gemma implementation)."""
    # Generate x values
    x = np.linspace(-4, 4, 400)

    # Define functions
    f = x**2 - 2
    g = x + 2

    # Solve for intersection: x^2 - 2 = x + 2  => x^2 - x - 4 = 0
    # Using quadratic formula: x = (-b +/- sqrt(b^2 - 4ac)) / 2a
    # a=1, b=-1, c=-4
    a, b, c = 1, -1, -4
    discriminant = b**2 - 4 * a * c

    x1 = (-b + math.sqrt(discriminant)) / (2 * a)
    x2 = (-b - math.sqrt(discriminant)) / (2 * a)

    y1 = x1**2 - 2
    y2 = x2**2 - 2

    # Create plot
    fig, ax = plt.subplots(figsize=(10, 6))

    ax.plot(x, f, label=r"$f(x) = x^2 - 2$", color="blue", linewidth=2)
    ax.plot(x, g, label=r"$g(x) = x + 2$", color="green", linewidth=2)

    # Mark intersection points
    ax.scatter([x1, x2], [y1, y2], color="red", s=100, zorder=5, label="Intersections")

    # Labeling the points with LaTeX and exact coordinates
    # Point 1
    label1 = f"$f(x)=g(x)$ $\text{{({x1:.3f}, {y1:.3f})}}$"
    ax.annotate(
        label1,
        xy=(x1, y1),
        xytext=(20, 20),
        textcoords="offset points",
        arrowprops=dict(arrowstyle="->", color="red"),
        bbox=dict(boxstyle="round,pad=0.5", fc="yellow", alpha=0.3),
        fontsize=10,
    )

    # Point 2
    label2 = f"$f(x)=g(x)$$\text{{({x2:.3f}, {y2:.3f})}}$"
    ax.annotate(
        label2,
        xy=(x2, y2),
        xytext=(-120, -40),
        textcoords="offset points",
        arrowprops=dict(arrowstyle="->", color="red"),
        bbox=dict(boxstyle="round,pad=0.5", fc="yellow", alpha=0.3),
        fontsize=10,
    )

    # Axis labels with LaTeX
    ax.set_xlabel(r"$x$", fontsize=14)
    ax.set_ylabel(r"$y$", fontsize=14)
    ax.set_title("Gemma Implementation: Function Intersection", fontsize=16)

    ax.grid(True, which="both", linestyle="--", alpha=0.5)
    ax.legend(loc="upper left")

    # Save the plot
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=150)
    plt.close(fig)
    print(f"Gemma's plot saved to {output}")


if __name__ == "__main__":
    plot_simple_functions()
