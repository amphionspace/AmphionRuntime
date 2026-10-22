/** A compact live waveform: the most recent input levels drawn as rounded bars, newest on the right. */
@Component
export struct LevelBars {
  @Prop levels: number[] = [];
  @Prop color: string = '#000000';
  @Prop barHeight: number = 28;
  barWidth: number = 3;

  build() {
    Row({ space: 3 }) {
      ForEach(this.levels, (level: number, index: number) => {
        Column()
          .width(this.barWidth)
          .height(Math.max(3, Math.min(1, level) * this.barHeight))
          .borderRadius(this.barWidth / 2)
          .backgroundColor(this.color)
          .opacity(0.35 + Math.min(1, level) * 0.65)
          .animation({ duration: 90, curve: Curve.Linear })
      }, (_level: number, index: number) => `${index}`)
    }
    .height(this.barHeight)
    .alignItems(VerticalAlign.Center)
  }
}
