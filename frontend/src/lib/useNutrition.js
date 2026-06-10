/* Scuffed OS — nutrition state for today.
   day/week stay null until the backend answers (screens render zeros/empties
   meanwhile). Water and meal-removal are optimistic; everything reconciles
   with the server afterwards, mirroring useTasks. */
import React from 'react'
import { api } from './api.js'

export function useNutrition({ onWaterChanged } = {}) {
  const [day, setDay] = React.useState(null)
  const [week, setWeek] = React.useState(null)

  const refresh = React.useCallback(() => {
    api.nutritionDay()
      .then((d) => { if (d) setDay(d) })
      .catch(() => {}) // backend down — keep what we have
    api.nutritionWeek()
      .then((w) => { if (w) setWeek(w) })
      .catch(() => {})
  }, [])

  React.useEffect(() => { refresh() }, [refresh])

  const logMeal = (fields) => {
    api.logMeal(fields)
      .then(() => refresh()) // totals/week come back computed server-side
      .catch(() => {})
  }

  const removeMeal = (id) => {
    setDay((d) => d && { ...d, meals: d.meals.filter((m) => m.id !== id) })
    api.deleteMeal(id)
      .then(() => refresh()) // reconcile totals
      .catch(() => {})
  }

  const addWater = () => {
    setDay((d) => d && { ...d, water: { ...d.water, cups: d.water.cups + 1 } })
    api.addWater(1)
      .then((w) => {
        if (w) setDay((d) => d && { ...d, water: w }) // server clamps
        // Hitting (or leaving) the goal flips a water-linked habit
        // server-side — let the habits hook know, after the server settled.
        if (onWaterChanged) onWaterChanged()
      })
      .catch(() => {})
  }

  return { day, week, logMeal, removeMeal, addWater, refresh }
}
