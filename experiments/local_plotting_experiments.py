import matplotlib.pyplot as plt
import numpy as np
import math
from matplotlib.animation import FuncAnimation
from pathlib import Path


def plot_simple_functions(output_path: str = "experiments/local_plot_simple.png") -> None:
    """Create a plot of f(x)=x^2-2 and g(x)=x+2 with the intersection marked per numerics.md instructions."""
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
    # The instruction says "the point where f(x)=g(x) marked". Since there are two, I'll mark both.
    ax.scatter([x1, x2], [y1, y2], color="red", s=100, zorder=5)

    # Labeling the points
    # "marked and labeled with 'f(x)=g(x)' and in a second line the exact coordinates"
    for xi, yi in zip([x1, x2], [y1, y2]):
        label = f"f(x)=g(x)\n({xi:.4f}, {yi:.4f})"
        ax.annotate(
            label,
            xy=(xi, yi),
            xytext=(20, 20),
            textcoords="offset points",
            arrowprops=dict(arrowstyle="->", color="red"),
            bbox=dict(boxstyle="round,pad=0.3", fc="yellow", alpha=0.3),
            fontsize=9,
            ha='left'
        )

    # Axis labels with LaTeX
    ax.set_xlabel(r"$x$", fontsize=14)
    ax.set_ylabel(r"$y$", fontsize=14)
    ax.set_title("Simple Plot: Function Intersection", fontsize=16)

    ax.grid(True, which="both", linestyle="--", alpha=0.5)
    ax.legend(loc="upper left")

    # Save the plot
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=150)
    plt.close(fig)
    print(f"Simple plot saved to {output}")


def animate_heat_equation(output_path: str = "experiments/heat_equation_animation.mp4") -> None:
    """Integrate the heat equation on a 2d rectangle with starting conditions of rectangle equal temperature t0=1 
    except for one x shaped area in the center which has temperature 5. Create an animation."""
    # Grid parameters
    nx, ny = 50, 50
    dx = 1.0 / (nx - 1)
    dy = 1.0 / (ny - 1)
    dt = 0.0001  # Small enough for stability
    alpha = 0.1  # Thermal diffusivity

    # Initial condition
    u = np.ones((nx, ny))

    # Create X-shaped area in the center
    center_x, center_y = nx // 2, ny // 2
    size = min(nx, ny) // 4
    for i in range(nx):
        for j in range(ny):
            # Distance from center
            dist_x = i - center_x
            dist_y = j - center_y
            # Check if it's on the X shape (approximate with |dx| approx |dy|)
            if abs(dist_x) == abs(dist_y) and abs(dist_x) <= size:
                u[i, j] = 5.0
            # A slightly thicker X for better visualization
            elif abs(abs(dist_x) - abs(dist_y)) <= 1 and abs(dist_x) <= size:
                u[i, j] = 5.0

    # Setup figure for animation
    fig, ax = plt.subplots()
    im = ax.imshow(u, cmap="hot", origin="lower", extent=[0, 1, 0, 1])
    plt.colorbar(im, label="Temperature")
    ax.set_title("2D Heat Equation Animation")

    def update(frame):
        nonlocal u
        # Finite difference step (FTCS)
        u_new = u.copy()
        # Vectorized update for interior points
        u_new[1:-1, 1:-1] = u[1:-1, 1:-1] + alpha * dt * (
            (u[2:, 1:-1] - 2*u[1:-1, 1:-1] + u[:-2, 1:-1]) / dx**2 +
            (u[1:-1, 2:] - 2*u[1:-1, 1:-1] + u[1:-1, :-2]) / dy**2
        )
        u = u_new
        im.set_array(u)
        return [im]

    # Total steps for animation
    num_steps = 200
    ani = FuncAnimation(fig, update, frames=num_steps, interval=50, blit=True)

    # Save animation
    # Note: requires ffmpeg or similar for mp4. If not available, it might fail.
    # We try to save as gif as a fallback if mp4 fails, or just show it.
    try:
        ani.save(output_path, writer="ffmpeg")
        print(f"Heat equation animation saved to {output_path}")
    except Exception as e:
        print(f"Could not save animation as mp4 (ffmpeg might be missing): {e}")
        print("Attempting to save as gif...")
        try:
            ani.save(output_path.replace(".mp4", ".gif"), writer="pillow")
            print(f"Heat equation animation saved as GIF to {output_path.replace('.mp4', '.gif')}")
        except Exception as e2:
            print(f"Failed to save animation: {e2}")

    plt.close(fig)


if __name__ == "__main__":
    print("Starting experiments...")
    plot_simple_functions()
    animate_heat_equation()
    print("Experiments complete.")
